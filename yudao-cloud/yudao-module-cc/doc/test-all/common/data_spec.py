# -*- coding: utf-8 -*-
"""
测试数据规格声明库
==================
需求背景:
    呼叫中心测试套件以数据库最新 6 条 cc_call_route(101-106) + 6 条 cc_flow_info(101-106)
    为固定测试规格。历史两套脚本各自硬编码 route id=7/8、flow_id=3、节点 id(NODE7_*)等,
    随流程/路由演进已大量失效。本模块把"数据库真值"收敛为单一声明式规格表,
    数据变更只需改本文件一处;同时提供动态提取节点 id 与逐项核对函数。

预期结果:
    - FLOW_SPECS: 以 flow_id 为键的声明式字典,含路由元数据 + 节点序列 + 断言关键词 + 转接期望;
    - get_flow_node_ids(flow_id, flow_data_json): 从实时 flow_data 动态提取节点 id 映射,消灭硬编码;
    - validate_specs(db): 逐路由/流程/坐席/坐席组/网关核对,返回缺失/不一致清单(空列表=全部一致)。

使用约定:
    - 场景脚本只通过 FLOW_SPECS + get_flow_node_ids 获取号码/流程/节点/断言信息,
      不得再写死 route id / flow id / node id。
"""
import json
from typing import Any, Dict, List, Optional

# 节点 type → 短名(用于 node_sequence 与 get_flow_node_ids 的键,也用于日志正则变量消歧)
_NODE_TYPE_SHORT = {
    "start-node": "start",
    "receive-node": "receive",
    "condition-node": "condition",
    "playback-node": "playback",
    "method-node": "method",
    "transfer-node": "transfer",
    "end-node": "end",
    "ai-node": "ai",
}

# ==================== 声明式规格表(数据变更只改这里) ====================
# 每条规格: route_id/name/regex/direction(1呼入2呼出)/delete_prefix/flow_id/
#           dtmf(主路径按键)/node_sequence(节点短名序列,按实际执行分支主链)/
#           transfer_expect(转接节点期望)/assert_keywords(后端日志关键词,供场景断言)/
#           scenarios(归属场景编号,仅用于可读性)
FLOW_SPECS: Dict[str, Dict[str, Any]] = {
    "101": {
        "route_id": 101,
        "name": "呼入-4001234",
        "regex": r"^(4001234).*",
        "direction": 1,
        "delete_prefix": "",
        "flow_id": 101,
        "dtmf": "1",
        # 主链: start → receive(按1) → 判断器1(IF result==1) → 放音(分支1) →
        #       method(1) → 判断器2(IF 非空) → transfer(坐席组1) → end
        # 说明: 库中 flow101 实际含 4 个 playback 节点(收号提示音/IF 分支放音/转接提示音等,
        #       主链分支放音), 声明数量须与数据库真值一致(validate_specs 按数量核对)。
        "node_sequence": ["start", "receive", "condition", "playback", "playback",
                          "playback", "playback", "method", "condition", "transfer", "end"],
        "transfer_expect": {"routeType": "4", "routeValue": "1"},  # routeType=4 坐席组, 组1
        "assert_keywords": ["流式播放完成", "分支命中", "ivr方法调用节点处理", "[转坐席组]"],
        "scenarios": [3],
    },
    "102": {
        "route_id": 102,
        "name": "呼出-内部电话",
        "regex": r"^(9#).*",
        "direction": 2,
        "delete_prefix": "9#",
        "flow_id": 102,
        "dtmf": None,
        # 主链: start → transfer(指定坐席, routeValue=${start-node.callee}) → end
        "node_sequence": ["start", "transfer", "end"],
        "transfer_expect": {"routeType": "1", "routeValue": "${start-node.callee}"},
        "assert_keywords": ["[删除前缀]", "[进入callRoute电话]"],
        "scenarios": [1, 5, 6],
    },
    "103": {
        "route_id": 103,
        "name": "呼出-自动外呼",
        "regex": r"^(00200).*",
        "direction": 2,
        "delete_prefix": "",
        "flow_id": 103,
        "dtmf": "1",
        "node_sequence": ["start", "receive", "end"],
        "transfer_expect": None,
        "assert_keywords": ["[自动外呼][号码路由匹配]"],
        "scenarios": [7],
    },
    "104": {
        "route_id": 104,
        "name": "呼出-客服组繁忙",
        "regex": r"^(00300).*",
        "direction": 2,
        "delete_prefix": "",
        "flow_id": 104,
        "dtmf": None,
        # 主链: start → playback(客服组繁忙请稍等再拨) → end(fileId=10)
        "node_sequence": ["start", "playback", "end"],
        "transfer_expect": None,
        "assert_keywords": ["客服组繁忙请稍等再拨"],
        "scenarios": [8],
    },
    "105": {
        "route_id": 105,
        "name": "呼出-外部电话",
        "regex": r"^(0#).*",
        "direction": 2,
        "delete_prefix": "0#",
        "flow_id": 105,
        "dtmf": None,
        # 主链: start → transfer(网关, routeType=2 routeValue=2) → end
        "node_sequence": ["start", "transfer", "end"],
        "transfer_expect": {"routeType": "2", "routeValue": "2"},  # routeType=2 网关, 网关2
        "assert_keywords": ["[删除前缀]"],
        "scenarios": [2],
    },
    "106": {
        "route_id": 106,
        "name": "呼出-满意度评价",
        "regex": r"^(00100).*",
        "direction": 2,
        "delete_prefix": "",
        "flow_id": 106,
        "dtmf": "1",
        # 主链: start → receive(按1) → method(1) → end(感谢您的评价，再见)
        "node_sequence": ["start", "receive", "method", "end"],
        "transfer_expect": None,
        "assert_keywords": ["感谢您的评价", "ivr方法调用节点处理"],
        "scenarios": [9],
    },
    "107": {
        "route_id": 107,
        "name": "呼出-AI对话",
        "regex": r"^(00600).*",
        "direction": 2,
        "delete_prefix": "",
        "flow_id": 107,
        "dtmf": None,
        # 主链: start(asr/tts) → ai(中断词=转人工) → condition(interruptWord EQ 转人工) →
        #       transfer(坐席1002) → end; else 分支 → playback(对话失败) → end(共 2 个 end)
        "node_sequence": ["start", "ai", "condition", "transfer", "end", "end"],
        "transfer_expect": {"routeType": "1", "routeValue": "1002"},  # routeType=1 指定坐席
        "assert_keywords": ["[进入callRoute电话]", "[ivrAI对话]", "中断词命中", "[ivr-转接-坐席处理节点]", "1002"],
        "scenarios": [10],
    },
}

# 坐席规格: name(SIP 分机号,即 cc_sys_agent.name 列) → 期望 user_id/domain
AGENT_SPECS = {
    "1001": {"user_id": 1, "domain": "1.com:1"},
    "1002": {"user_id": 100, "domain": "1.com:1"},
    "1003": {"user_id": 104, "domain": "1.com:1"},
}

# 坐席组规格: 组 id → 期望名称 + 至少包含的坐席 name 集合(任一就绪成员即可接听)
AGENT_GROUP_SPEC = {"id": 1, "members": ["1001", "1002", "1003"]}

# 第三方网关规格: 网关 id → 期望 name/username/address/status(0=启用)
GATEWAY_SPEC = {
    "id": 2,
    "name": "第三方网关",
    "username": "18600000000",
    "address": "62.234.191.165",
    "status": 0,
}


def get_flow_node_ids(flow_id: int, flow_data_json: Any) -> Dict[str, List[str]]:
    """
    从实时 flow_data 动态提取节点 id 映射(按 type 分组,同 type 按 nodes 数组序消歧)。

    需求背景: flow_data 的节点顺序不可靠(end 节点可能出现在前),且历史脚本硬编码
    NODE7_* 节点 id 随流程重绘频繁失效。本函数只读 flow_data 中的 type 字段,
    返回 {短名: [节点id, ...]},同 type 多节点时按 nodes 数组出现顺序下标消歧。

    :param flow_id: 流程 id(仅用于异常消息定位,不参与提取逻辑)
    :param flow_data_json: cc_flow_info.flow_data 列(JSON 字符串或已解析 dict)
    :return: {短名: [节点id, ...]} 映射;无 nodes 或解析失败返回空 dict
    :raises ValueError: flow_data_json 无法解析为含 nodes 数组的 JSON 时抛出
    """
    data = flow_data_json
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(
                "flow_id=%s 的 flow_data 不是合法 JSON: %s" % (flow_id, e)
            ) from e
    if not isinstance(data, dict):
        raise ValueError("flow_id=%s 的 flow_data 顶层不是 JSON 对象" % flow_id)
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return {}

    result: Dict[str, List[str]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type", "")
        nid = node.get("id")
        short = _NODE_TYPE_SHORT.get(ntype, ntype)
        if nid is not None:
            result.setdefault(short, []).append(str(nid))
    return result


def _parse_flow_data(flow_data_json: Any) -> Dict:
    """解析 flow_data(JSON 字符串或 dict),失败抛 ValueError,供 validate_specs 复用。"""
    if isinstance(flow_data_json, str):
        try:
            return json.loads(flow_data_json)
        except json.JSONDecodeError as e:
            raise ValueError("flow_data 不是合法 JSON: %s" % e) from e
    if isinstance(flow_data_json, dict):
        return flow_data_json
    raise ValueError("flow_data 类型异常: %s" % type(flow_data_json).__name__)


def validate_specs(db) -> List[str]:
    """
    逐项核对数据库真值是否与 FLOW_SPECS / AGENT_SPECS / AGENT_GROUP_SPEC / GATEWAY_SPEC 一致。

    需求背景: 测试规格以数据库为基准,执行前必须先确认库中路由/流程/坐席/坐席组/网关
    未漂移,否则场景断言会误报。核对失败返回人类可读的缺失/不一致清单。

    :param db: DbHelper 实例(需已 connect)
    :return: 缺失/不一致清单(字符串列表);空列表表示全部一致。核对本身抛异常则列表含异常描述。
    """
    issues: List[str] = []
    # 路由/流程 ID 从 FLOW_SPECS 动态推导, 新增规格无需再改核对查询
    spec_ids = sorted({spec["route_id"] for spec in FLOW_SPECS.values()})
    flow_ids = sorted({spec["flow_id"] for spec in FLOW_SPECS.values()})
    id_placeholders = ",".join(["%s"] * len(spec_ids))

    # ---- 1. 路由核对 ----
    route_rows = db.query(
        "SELECT id, name, route_num, delete_prefix, type, status, flow_id "
        "FROM cc_call_route WHERE id IN (%s) AND deleted = 0" % id_placeholders,
        tuple(spec_ids)
    )
    route_by_id = {int(r["id"]): r for r in route_rows}
    for fid, spec in FLOW_SPECS.items():
        rid = spec["route_id"]
        row = route_by_id.get(rid)
        if row is None:
            issues.append("路由缺失: route_id=%s (flow_id=%s name=%s)" % (rid, fid, spec["name"]))
            continue
        if str(row.get("name", "")) != spec["name"]:
            issues.append("路由 %s 名称不一致: 期望=%s 实际=%s" % (rid, spec["name"], row.get("name")))
        if str(row.get("route_num", "")) != spec["regex"]:
            issues.append("路由 %s route_num 不一致: 期望=%s 实际=%s" % (rid, spec["regex"], row.get("route_num")))
        if str(row.get("delete_prefix", "") or "") != spec["delete_prefix"]:
            issues.append("路由 %s delete_prefix 不一致: 期望=%r 实际=%r"
                          % (rid, spec["delete_prefix"], row.get("delete_prefix")))
        if int(row.get("type", 0)) != spec["direction"]:
            issues.append("路由 %s type 不一致: 期望=%s 实际=%s" % (rid, spec["direction"], row.get("type")))
        if int(row.get("status", 0)) != 1:
            issues.append("路由 %s 未启用: status=%s" % (rid, row.get("status")))
        if int(row.get("flow_id", 0)) != spec["flow_id"]:
            issues.append("路由 %s flow_id 不一致: 期望=%s 实际=%s" % (rid, spec["flow_id"], row.get("flow_id")))

    # ---- 2. 流程核对(存在性 + 节点序列 + 转接期望) ----
    flow_rows = db.query(
        "SELECT id, flow_data FROM cc_flow_info WHERE id IN (%s) AND deleted = 0" % id_placeholders,
        tuple(flow_ids)
    )
    flow_by_id = {int(r["id"]): r for r in flow_rows}
    for fid, spec in FLOW_SPECS.items():
        fid_int = spec["flow_id"]
        row = flow_by_id.get(fid_int)
        if row is None:
            issues.append("流程缺失: flow_id=%s (name=%s)" % (fid_int, spec["name"]))
            continue
        try:
            node_ids = get_flow_node_ids(fid_int, row.get("flow_data"))
        except ValueError as e:
            issues.append(str(e))
            continue
        if not node_ids:
            issues.append("流程 %s flow_data 无 nodes 或为空" % fid_int)
            continue
        # 节点序列核对: 声明序列中每种短名的数量须与库中该 type 节点数量一致
        seq = spec["node_sequence"]
        declared_counts: Dict[str, int] = {}
        for short in seq:
            declared_counts[short] = declared_counts.get(short, 0) + 1
        for short, expected_cnt in declared_counts.items():
            actual_cnt = len(node_ids.get(short, []))
            if actual_cnt != expected_cnt:
                issues.append("流程 %s 节点数量不一致: type=%s 期望=%s 实际=%s"
                              % (fid_int, short, expected_cnt, actual_cnt))
        # 转接节点期望核对(仅核对字面量 routeType/routeValue)
        if spec.get("transfer_expect"):
            transfer_ids = node_ids.get("transfer", [])
            if not transfer_ids:
                issues.append("流程 %s 声明有转接节点但 flow_data 无 transfer 节点" % fid_int)
            else:
                try:
                    data = _parse_flow_data(row.get("flow_data"))
                    for node in data.get("nodes", []):
                        if node.get("type") != "transfer-node":
                            continue
                        props = node.get("properties", {})
                        exp = spec["transfer_expect"]
                        if str(props.get("routeType", "")) != exp.get("routeType"):
                            issues.append("流程 %s 转接节点 routeType 不一致: 期望=%s 实际=%s"
                                          % (fid_int, exp.get("routeType"), props.get("routeType")))
                        # routeValue 为 ${...} 变量时不比对字面量
                        rv = exp.get("routeValue", "")
                        if not str(rv).startswith("${"):
                            if str(props.get("routeValue", "")) != rv:
                                issues.append("流程 %s 转接节点 routeValue 不一致: 期望=%s 实际=%s"
                                              % (fid_int, rv, props.get("routeValue")))
                except ValueError as e:
                    issues.append(str(e))

    # ---- 3. 坐席核对 ----
    agent_rows = db.query(
        "SELECT id, name, user_id, domain, status FROM cc_sys_agent "
        "WHERE name IN ('1001','1002','1003') AND deleted = 0"
    )
    agent_by_name = {str(r["name"]): r for r in agent_rows}
    for name, spec in AGENT_SPECS.items():
        row = agent_by_name.get(name)
        if row is None:
            issues.append("坐席缺失: %s" % name)
            continue
        if int(row.get("user_id", 0)) != spec["user_id"]:
            issues.append("坐席 %s user_id 不一致: 期望=%s 实际=%s" % (name, spec["user_id"], row.get("user_id")))
        if str(row.get("domain", "") or "") != spec["domain"]:
            issues.append("坐席 %s domain 不一致: 期望=%s 实际=%s" % (name, spec["domain"], row.get("domain")))
        if int(row.get("status", 0)) != 1:
            issues.append("坐席 %s status 异常: 期望=1 实际=%s" % (name, row.get("status")))

    # ---- 4. 坐席组核对 ----
    group_rows = db.query(
        "SELECT id, name FROM cc_sys_agent_group WHERE id = 1 AND deleted = 0"
    )
    if not group_rows:
        issues.append("坐席组缺失: id=1")
    else:
        rel_rows = db.query(
            "SELECT rel.agent_id, a.name FROM cc_sys_agent_group_rel rel "
            "LEFT JOIN cc_sys_agent a ON a.id = rel.agent_id AND a.deleted = 0 "
            "WHERE rel.group_id = 1 AND rel.deleted = 0"
        )
        member_names = {str(r.get("name")) for r in rel_rows if r.get("name")}
        for member in AGENT_GROUP_SPEC["members"]:
            if member not in member_names:
                issues.append("坐席组1 缺少成员: %s (当前成员=%s)" % (member, sorted(member_names)))

    # ---- 5. 第三方网关核对 ----
    gw_rows = db.query(
        "SELECT id, name, username, address, status FROM cc_sipproxy_gateway "
        "WHERE id = 2 AND deleted = 0"
    )
    if not gw_rows:
        issues.append("第三方网关缺失: id=2")
    else:
        gw = gw_rows[0]
        gspec = GATEWAY_SPEC
        if str(gw.get("name", "")) != gspec["name"]:
            issues.append("网关2 name 不一致: 期望=%s 实际=%s" % (gspec["name"], gw.get("name")))
        if str(gw.get("username", "")) != gspec["username"]:
            issues.append("网关2 username 不一致: 期望=%s 实际=%s" % (gspec["username"], gw.get("username")))
        if str(gw.get("address", "") or "") != gspec["address"]:
            issues.append("网关2 address 不一致: 期望=%s 实际=%s" % (gspec["address"], gw.get("address")))
        if int(gw.get("status", 0)) != gspec["status"]:
            issues.append("网关2 status 不一致: 期望=%s(启用) 实际=%s" % (gspec["status"], gw.get("status")))

    return issues

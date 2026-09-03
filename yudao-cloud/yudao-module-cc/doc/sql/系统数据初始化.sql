SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 系统数据初始化
-- 菜单
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫中心', '', 1, 60, 0, '/cc', 'ep:phone', '', '', 0);
-- 呼叫中心菜单ID
SELECT @parentIdOne := LAST_INSERT_ID();

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('配置管理', '', 1, 1, @parentIdOne, 'cc_config', '', '', '', 0);
-- 配置管理菜单ID
SELECT @parentIdTwo := LAST_INSERT_ID();

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs配置管理', '', 2, 0, @parentIdTwo, 'fs-config', '', 'cc/fsconfig/index', 'FsConfig', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs管理配置查询', 'cc:fs-config:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs管理配置创建', 'cc:fs-config:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs管理配置更新', 'cc:fs-config:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs管理配置删除', 'cc:fs-config:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs管理配置导出', 'cc:fs-config:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs访问控制管理', '', 2, 1, @parentIdTwo, 'fs-acl', '', 'cc/fsacl/index', 'FsAcl', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs访问控制查询', 'cc:fs-acl:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs访问控制创建', 'cc:fs-acl:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs访问控制更新', 'cc:fs-acl:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs访问控制删除', 'cc:fs-acl:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs访问控制导出', 'cc:fs-acl:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs拨号计划管理', '', 2, 2, @parentIdTwo, 'fs-dialplan', '', 'cc/fsdialplan/index', 'FsDialplan', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs拨号计划查询', 'cc:fs-dialplan:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs拨号计划创建', 'cc:fs-dialplan:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs拨号计划更新', 'cc:fs-dialplan:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs拨号计划删除', 'cc:fs-dialplan:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('fs拨号计划导出', 'cc:fs-dialplan:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('SIP代理网关管理', '', 2, 6, @parentIdTwo, 'sipproxygateway', '', 'cc/sipproxygateway/index', 'SipProxyGateway',
        0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('SIP代理网关查询', 'cc:sip-proxy-gateway:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('SIP代理网关创建', 'cc:sip-proxy-gateway:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('SIP代理网关更新', 'cc:sip-proxy-gateway:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('SIP代理网关删除', 'cc:sip-proxy-gateway:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('SIP代理网关导出', 'cc:sip-proxy-gateway:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫管理', '', 1, 2, @parentIdOne, 'cc_call', '', '', '', 0);
-- 呼叫管理菜单ID
SELECT @parentIdThree := LAST_INSERT_ID();

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席管理', '', 2, 1, @parentIdThree, 'sys-agent', '', 'cc/sysagent/index', 'SysAgent', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席管理查询', 'cc:sys-agent:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席管理创建', 'cc:sys-agent:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席管理更新', 'cc:sys-agent:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席管理删除', 'cc:sys-agent:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席管理导出', 'cc:sys-agent:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席组管理', '', 2, 2, @parentIdThree, 'sys-agent-group', '', 'cc/sysagentgroup/index', 'SysAgentGroup', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席组查询', 'cc:sys-agent-group:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席组创建', 'cc:sys-agent-group:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席组更新', 'cc:sys-agent-group:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席组删除', 'cc:sys-agent-group:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('坐席组导出', 'cc:sys-agent-group:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码管理', '', 2, 3, @parentIdThree, 'call-display', '', 'cc/calldisplay/index', 'CallDisplay', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码管理查询', 'cc:call-display:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码管理创建', 'cc:call-display:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码管理更新', 'cc:call-display:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码管理删除', 'cc:call-display:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码管理导出', 'cc:call-display:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码路由管理', '', 2, 4, @parentIdThree, 'call-route', '', 'cc/callroute/index', 'CallRoute', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码路由查询', 'cc:call-route:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码路由创建', 'cc:call-route:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码路由更新', 'cc:call-route:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码路由删除', 'cc:call-route:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('号码路由导出', 'cc:call-route:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('电话归属地管理', '', 2, 5, @parentIdThree, 'sys-phone-location', '', 'cc/sysphonelocation/index',
        'SysPhoneLocation', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('电话归属地查询', 'cc:phone-location:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('电话归属地创建', 'cc:phone-location:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('电话归属地更新', 'cc:phone-location:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('电话归属地删除', 'cc:phone-location:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('电话归属地导出', 'cc:phone-location:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音引擎管理', '', 2, 6, @parentIdThree, 'sys-voice-engine', '', 'cc/sysvoiceengine/index', 'SysVoiceEngine',
        0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音引擎查询', 'cc:sys-voice-engine:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音引擎创建', 'cc:sys-voice-engine:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音引擎更新', 'cc:sys-voice-engine:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音引擎删除', 'cc:sys-voice-engine:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音引擎导出', 'cc:sys-voice-engine:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音文件管理', '', 2, 7, @parentIdThree, 'sys-voice-file', '', 'cc/sysvoicefile/index', 'SysVoiceFile', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音文件查询', 'cc:sys-voice-file:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音文件创建', 'cc:sys-voice-file:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音文件更新', 'cc:sys-voice-file:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音文件删除', 'cc:sys-voice-file:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('语音文件导出', 'cc:sys-voice-file:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫记录', '', 2, 8, @parentIdThree, 'call-record', '', 'cc/callrecord/index', 'CallRecord', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫记录查询', 'cc:call-record:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫记录创建', 'cc:call-record:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫记录更新', 'cc:call-record:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫记录删除', 'cc:call-record:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('呼叫记录导出', 'cc:call-record:export', 3, 5, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('外呼任务', '', 2, 9, @parentIdThree, 'autocall-task', '', 'cc/autocalltask/index', 'AutocallTask', 0);
-- 按钮父级菜单ID
SELECT @parentId := LAST_INSERT_ID();
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('外呼任务查询', 'cc:autocall-task:query', 3, 1, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('外呼任务创建', 'cc:autocall-task:create', 3, 2, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('外呼任务更新', 'cc:autocall-task:update', 3, 3, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('外呼任务删除', 'cc:autocall-task:delete', 3, 4, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('外呼任务执行', 'cc:autocall-task:execute', 3, 5, @parentId, '', '', '', '', 0);
INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('外呼任务导出', 'cc:autocall-task:export', 3, 6, @parentId, '', '', '', '', 0);

INSERT INTO system_menu (name, permission, type, sort, parent_id, path, icon, component, component_name, status)
VALUES ('业务示例', '', 2, 3, @parentIdOne, 'biz-example', '', 'cc/bizexample/index', 'CcBizExample', 0);

-- 字典
INSERT INTO system_dict_type (name, type)
VALUES ('cc-语音引擎厂商', 'cc_sys_voice_manufacturer_type');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-语音引擎类型', 'cc_sys_voice_engine');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-坐席组-溢出策略', 'cc_sys_agent_group_overflow_type');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-坐席组-全忙策略', 'cc_sys_agent_group_full_busy_type');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-坐席组-策略类型', 'cc_sys_agent_group_strategy_type');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-路由启用状态', 'cc_call_route_status');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-路由方向类型', 'cc_call_route_direction_type');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-挂机方向', 'cc_call_hangup_dir');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-应答标识', 'cc_call_answer_flag');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-呼叫方式', 'cc_call_direction');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-呼叫状态', 'cc_call_state');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-语音类型', 'cc_sys_voice_type');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-坐席状态', 'cc_sys_agent_online_status');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-sip分机状态', 'cc_sip_subscriber_status');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-fs拨号计划内容类型', 'cc_fs_dialplan_context_name');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-fs内容格式', 'cc_fs_context_format');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-fs在线状态', 'cc_fs_online_status');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-fs访问控制类型', 'cc_fs_acl_type');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-IVR内部方法', 'cc_ivr_interior_method');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-IVR条件操作符', 'cc_ivr_condition_operator');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-网关注册模式', 'cc_sipproxy_gateway_register_mode');
INSERT INTO system_dict_type (name, type)
VALUES ('cc-网关注册状态', 'cc_sipproxy_gateway_register_status');

INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, 'IP直连', '0', 'cc_sipproxy_gateway_register_mode');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '注册模式', '1', 'cc_sipproxy_gateway_register_mode');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '离线', '0', 'cc_sipproxy_gateway_register_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '在线', '1', 'cc_sipproxy_gateway_register_status');

INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '阿里', '2', 'cc_sys_voice_manufacturer_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, 'asr', '1', 'cc_sys_voice_engine');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, 'tts', '2', 'cc_sys_voice_engine');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '挂机', '0', 'cc_sys_agent_group_overflow_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '转IVR', '1', 'cc_sys_agent_group_overflow_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '排队', '0', 'cc_sys_agent_group_full_busy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '溢出', '1', 'cc_sys_agent_group_full_busy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '挂机', '2', 'cc_sys_agent_group_full_busy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '随机', '0', 'cc_sys_agent_group_strategy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '轮询', '1', 'cc_sys_agent_group_strategy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '最长空闲时间', '2', 'cc_sys_agent_group_strategy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (3, '当天最少应答次数', '3', 'cc_sys_agent_group_strategy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (4, '最长话后时长', '4', 'cc_sys_agent_group_strategy_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '未启用', '0', 'cc_call_route_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '启用', '1', 'cc_call_route_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '呼入', '1', 'cc_call_route_direction_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '呼出', '2', 'cc_call_route_direction_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '主叫挂机', '1', 'cc_call_hangup_dir');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '被叫挂机', '2', 'cc_call_hangup_dir');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (3, '系统挂机', '3', 'cc_call_hangup_dir');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '接通', '0', 'cc_call_answer_flag');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '坐席未接用户未接', '1', 'cc_call_answer_flag');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '坐席接通用户未接通', '2', 'cc_call_answer_flag');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (3, '用户接通坐席未接通', '3', 'cc_call_answer_flag');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '呼出', '1', 'cc_call_direction');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '呼入', '2', 'cc_call_direction');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '成功', '1', 'cc_call_state');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '失败', '2', 'cc_call_state');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '手动上传', '1', 'cc_sys_voice_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '语音合成', '2', 'cc_sys_voice_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '空闲', '1', 'cc_sys_agent_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '忙碌', '2', 'cc_sys_agent_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (3, '勿扰', '3', 'cc_sys_agent_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (4, '离线', '4', 'cc_sys_agent_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (5, '通话中', '5', 'cc_sys_agent_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (6, '振铃中', '6', 'cc_sys_agent_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (7, '话后', '7', 'cc_sys_agent_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '未开通', '0', 'cc_sip_subscriber_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '开通', '1', 'cc_sip_subscriber_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, 'public', 'public', 'cc_fs_dialplan_context_name');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, 'default', 'default', 'cc_fs_dialplan_context_name');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, 'xml格式', 'xml', 'cc_fs_context_format');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, 'json格式', 'json', 'cc_fs_context_format');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (0, '在线', '0', 'cc_fs_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '下线', '1', 'cc_fs_online_status');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '允许', 'allow', 'cc_fs_acl_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '拒绝', 'deny', 'cc_fs_acl_type');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '测试方法', '1', 'cc_ivr_interior_method');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (1, '为空', 'IS_EMPTY', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (2, '不为空', 'IS_NOT_EMPTY', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (3, '包含', 'CONTAINS', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (4, '不包含', 'NOT_CONTAINS', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (5, '等于', 'EQ', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (6, '不等于', 'NE', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (7, '大于', 'GT', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (8, '大于等于', 'GTE', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (9, '小于', 'LT', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (10, '小于等于', 'LTE', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (11, '长度等于', 'LENGTH_EQ', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (12, '长度不等于', 'LENGTH_NE', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (13, '长度大于', 'LENGTH_GT', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (14, '长度大于等于', 'LENGTH_GTE', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (15, '长度小于', 'LENGTH_LT', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (16, '长度小于等于', 'LENGTH_LTE', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (17, '为真', 'IS_TRUE', 'cc_ivr_condition_operator');
INSERT INTO system_dict_data (sort, label, value, dict_type)
VALUES (18, '不为真', 'IS_NOT_TRUE', 'cc_ivr_condition_operator');


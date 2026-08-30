#!/usr/bin/env python3
# 分析后端日志中的 CHANNEL_PARK 事件, 输出各事件的关键消息头字段
import re, json

log_file = '/Users/wenjiaqi/Documents/ipcc/logs/yudao-server.log'

pattern = r'ChannelParkEslEventHandler handle address:([^\s]+) EslEvent:(\{.*"eventName":"CHANNEL_PARK".*?\})\]\s*$'

results = []
with open(log_file, 'r', encoding='utf-8') as f:
    for line in f:
        if 'ChannelParkEslEventHandler handle' not in line:
            continue
        match = re.search(pattern, line)
        if not match:
            continue
        try:
            ev = json.loads(match.group(2))
            h = ev.get('eventHeaders', {})
            d = h.get('Caller-Direction', '')
            ld = h.get('Caller-Logical-Direction', '')
            ua = h.get('variable_sip_user_agent', '')
            ca = h.get('Caller-Caller-ID-Number', '')
            cb = h.get('Caller-Destination-Number', '')
            gw = h.get('variable_sip_h_X-Gateway-Id', '')
            tid = h.get('variable_task_id', '')
            ch = h.get('Channel-Name', '')
            profile = h.get('variable_sofia_profile_name', '')
            results.append((d, ld, ua, ca, cb, gw, tid, profile, ch))
        except Exception as e:
            pass

print(f'共找到 {len(results)} 个 CHANNEL_PARK 事件')
for i, (d, ld, ua, ca, cb, gw, tid, pr, ch) in enumerate(results):
    print(
        f'[{i:2d}] Dir={d:8s} LD={ld:8s} UA={ua[:25]:25s} From={ca:12s} To={cb:12s} GW={gw:6s} TID={tid:5s} Prof={pr:10s}')

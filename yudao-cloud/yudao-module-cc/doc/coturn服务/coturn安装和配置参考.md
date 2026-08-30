参考：https://blog.csdn.net/gitblog_00765/article/details/152424973

``` shell
cd /opt
git clone https://gitcode.com/GitHub_Trending/co/coturn
cd coturn

mkdir -p /etc/coturn
mkdir -p /etc/coturn/certs
cp docker/coturn/turnserver.conf /etc/coturn/

# 编辑配置文件 /etc/coturn/turnserver.conf，关键配置项：
# 基础配置
listening-port=3478          # 监听端口
tls-listening-port=5349      # TLS监听端口
min-port=49152               # 最小中继端口
max-port=49200               # 最大中继端口
realm=your.domain.com        # 认证域名

# 安全配置
lt-cred-mech                 # 启用长期凭证机制
fingerprint                  # 启用消息指纹验证
no-tlsv1                     # 禁用TLSv1
no-tlsv1_1                   # 禁用TLSv1.1
user=yudao-cc:yudao-cc       # 认证用户名和密码

# 日志配置
syslog                       # 输出日志到syslog
log-file=/var/log/turnserver.log  # 日志文件路径

```

# 启动coturn容器

docker run -d --name coturn --network=host -v /etc/coturn/turnserver.conf:/etc/coturn/turnserver.conf -v
/etc/coturn/certs:/etc/coturn/certs coturn/coturn

# 测试coturn

https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/

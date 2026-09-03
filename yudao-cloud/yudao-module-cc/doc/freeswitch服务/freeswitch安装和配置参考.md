# freeswitch docker 安装和配置

## 拉取国内镜像

docker pull swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/safarov/freeswitch:1.10.12

## 修改镜像名

docker tag swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/safarov/freeswitch:1.10.12 freeswitch:1.10.12

## 需要使用的端口，在配置文件中修改

内部sip服务 15560 15561 （默认配置 5060 5061）

外部sip服务 15580 15581 （默认配置 5080 5081）

客户端链接服务 18021 （默认配置为8021）

TP 媒体端口 UDP 16384 - 32768 （默认配置）

## 创建容器复制配置文件

docker run -d --name freeswitch freeswitch:1.10.12

## 复制出配置文件

docker cp freeswitch:/etc/freeswitch /etc

windows中

docker cp freeswitch:/etc/freeswitch D:\docker

## ~~复制出语音文件~~

~~网络允许的请的情况下创建容器会自动下载下载音频文件。
容器内语音文件有可能为空，自行从官网源码中复制也可忽略系统中有语音文件上传的管理（普通业务用不到软件自带的语音文件）~~

~~docker cp freeswitch:/usr/share/freeswitch/sounds /etc/freeswitch~~

~~windows中~~

~~docker cp freeswitch:/usr/share/freeswitch/sounds D:\docker\freeswitch~~

## 删除容器

docker stop freeswitch

docker rm freeswitch

## 配置freeswitch

### 增加模块

cd /etc/freeswitch/autoload_configs/

vim modules.conf.xml

#### 添加以下内容

``` xml

<!-- 作用是通过 HTTP/HTTPS 协议从外部服务器动态获取 XML 配置，替代或补充 FreeSWITCH 的本地 XML 配置文件（如用户目录、拨号计划、网关配置等） -->
<load module="mod_xml_curl"/>

<!-- 注释掉无用模块 避免日志报错 -->
<!--  <load module="mod_signalwire"/> -->
```

### 修改xml_curl.conf.xml

cd /etc/freeswitch/autoload_configs/

vim xml_curl.conf.xml

#### 添加以下内容

``` xml

<binding name="all configs">
<!-- java程序的接口地址 -->
   <param name="gateway-url" value="http://java程序ip:48080/admin-api/cc/fs/curl/api" bindings="dialplan|configuration|phrases"/>
   <!-- 请求超时时间（毫秒） -->
      <param name="timeout" value="2000"/>
</binding>

```

### 修改event_socket.conf.xml

cd /etc/freeswitch/autoload_configs/

vim event_socket.conf.xml

#### 修改以下内容

``` xml

  <settings>
    <param name="nat-map" value="false"/>
    <param name="listen-ip" value="::"/>
    <param name="listen-port" value="18021"/>
    <param name="password" value="<密码>"/>
    <param name="apply-inbound-acl" value="event_socket.auto"/>
    <!--<param name="stop-on-bind-error" value="true"/>-->
  </settings>
  
```

### 修改acl.conf.xml

cd /etc/freeswitch/autoload_configs/

vim acl.conf.xml

#### 修改或新增以下配置

``` xml

<list name="event_socket.auto" defalut="allow">
    <node type="allow" cidr="需要连接socket的ip地址/掩码" />
</list>

```

### 修改var.xml

cd /etc/freeswitch

vim var.xml

#### 添加/修改以下内容

``` xml

<!-- 全局默认密码，通常无用，使用其他模块出现密码错误时可尝试使用这个密码 -->
<X-PRE-PROCESS cmd="set" data="default_password=<密码>"/>

<X-PRE-PROCESS cmd="stun-set" data="external_rtp_ip=公网ip"/>
<X-PRE-PROCESS cmd="stun-set" data="external_sip_ip=公网ip"/>

<!-- Internal SIP Profile -->
<X-PRE-PROCESS cmd="set" data="internal_auth_calls=false"/>
<X-PRE-PROCESS cmd="set" data="internal_sip_port=15560"/>
<X-PRE-PROCESS cmd="set" data="internal_tls_port=15561"/>
<X-PRE-PROCESS cmd="set" data="internal_ssl_enable=false"/>
<!-- External SIP Profile -->
<X-PRE-PROCESS cmd="set" data="external_auth_calls=false"/>
<X-PRE-PROCESS cmd="set" data="external_sip_port=15580"/>
<X-PRE-PROCESS cmd="set" data="external_tls_port=15581"/>
<X-PRE-PROCESS cmd="set" data="external_ssl_enable=false"/>

```

## 启动freeswitch

映射目录 参考镜像介绍地址 https://hub.docker.com/r/safarov/freeswitch

设置 -e SOUND_RATES=8000:16000 -e SOUND_TYPES=music:zh-cn-sinmei 会自动下载语音文件30分钟

尝试 去掉，可能就不会下载（实际业务中也用不到）

mac

docker run -d --net=host --name freeswitch --log-opt max-size=10m --log-opt max-file=3 -e TZ=Asia/Shanghai -v
/etc/freeswitch:/etc/freeswitch -v /etc/freeswitch/sounds:/usr/share/freeswitch/sounds freeswitch:1.10.12

windows中

docker run -d --net=host --name freeswitch --log-opt max-size=10m --log-opt max-file=3 -e TZ=Asia/Shanghai -v D:
\docker\freeswitch:/etc/freeswitch -v D:\docker\freeswitch/sounds:/usr/share/freeswitch/sounds -v D:
\docker\freeswitch/ssl/certs/freeswitch-selfsigned.crt:/etc/ssl/certs/ca-certificates.crt freeswitch:1.10.12

查看容器运行日志

docker logs -f freeswitch

**出现下载语音文件的情况**

网络允许情况下会出现下载语音文件日志（耗时30分钟左右），有时修改配置也不生效

日志：freeswitch-sounds-mu

**ssl错误未解决（不影响使用**）

[ERR] mod_signalwire.c:393 Curl Result 77, Error: error setting certificate file: /etc/ssl/certs/ca-certificates.crt

或

[ERR] mod_signalwire.c:393 Curl Result 60, Error: SSL certificate problem: unable to get local issuer certificate

## 进入daocker

docker exec -it freeswitch sh

## 查看日志 是否启动成功

出现 freeswitch代码图标 和 FreeSWITCH Started 为成功

tail -f -n 100 /var/log/freeswitch/freeswitch.log

## 客户端链接 对应event_socket.conf.xml中配置

docker exec -it freeswitch sh

fs_cli -P 18021 -p <密码>

出现 Error Connecting 错误，多是 freeswitch 未启动成功

查看启动日志或进入docker的/etc/freeswitch 配置目录 检查配置是否生效 不生效删除容器重新创建

## 常用命令 (连接客户端后)

### 开启/关闭internal报文追踪

sofia profile internal siptrace on/off

### 开启/关闭external报文追踪

sofia profile external siptrace on/off

### 开启/关闭全部报文追踪

sofia global siptrace on/off

### 查看sofia状态

sofia status

### 查看profile状态

sofia status profile external

sofia status profile internal

### 重新加载profile

sofia profile external restart

sofia profile internal restart

### 开启最大级别日志

sofia loglevel all 9

### 列出网关状态

sofia status gateway

### 修改完配置文件之后，执行该命令更新freeswitch.xml中配置的文件到内存

reloadxml

### 查看支持编码类型

show codec

### 重新载入模块配置

reload 模块名称

### 加载配置网关

sofia profile external rescan

### 查看sip注册信息

sofia status profile internal reg

### 抓包

sudo tcpdump -i any udp -v -w /opt/tcpdump.pcap

### fs_cli 发送invite 测试

originate {return_ring_ready=true,sip_contact_user=00000,ring_asr=true,fire_asr_events=true,absolute_codec_string=^^:
G722:PCMU:
PCMA,origination_caller_id_number=00000,origination_caller_id_name=00000,media_webrtc=true}sofia/external/1002@<B服务器内网>:
5561;transport=tcp &park () 
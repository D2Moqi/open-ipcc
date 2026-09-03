"""
Playwright 浏览器自动化测试封装
================================
本模块封装了基于 Playwright 的浏览器自动化操作,用于驱动本地前端 Vue 页面
(http://localhost:80) 完成呼叫中心系统的端到端测试。

主要功能:
  - 启动/关闭 Chromium 浏览器(自动授予 WebRTC 所需的摄像头/麦克风权限)
  - 模拟坐席登录系统(admin/<密码>)
  - 操作软电话组件(SoftPhone.vue)完成 SIP 签入/签出
  - 切换就绪/忙碌状态
  - 发起呼叫、接听来电、挂断、拒接
  - 通话中保持/恢复、静音/取消静音、发送 DTMF
  - 多通话会话切换
  - 状态查询与截图保存

依赖: playwright==1.42.0
"""

import os
import time
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from config import LOCAL_FRONTEND_URL


class BrowserTest:
    """Playwright浏览器自动化封装,用于驱动前端Vue页面进行端到端测试"""

    def __init__(self, headless: bool = False, slow_mo: int = 100, fake_audio_wav: str = None):
        """
        初始化浏览器测试实例
        :param headless: 是否无头模式(默认False,便于观察测试过程)
        :param slow_mo: 操作慢动作毫秒数(便于观察,默认100ms)
        :param fake_audio_wav: 假麦克风音频文件路径(循环播放,供 AI 对话等 ASR 语音注入场景;
            为空时使用默认假设备静音流)
        """
        # 浏览器运行模式:无头模式下不显示窗口,适合CI;有头模式便于调试观察
        self.headless = headless
        # 慢动作:每个操作之间暂停的毫秒数,便于人眼观察测试过程
        self.slow_mo = slow_mo
        # 假麦克风音频文件(循环播放): 非空时经 --use-file-for-fake-audio-capture 注入,
        # 使 WebRTC 上行音频持续包含目标语音(如"转人工"), 供 ASR 识别命中中断词
        self.fake_audio_wav = fake_audio_wav
        # Playwright 实例,在 start() 中创建
        self._playwright = None
        # 浏览器实例
        self._browser: Browser = None
        # 默认浏览器上下文(授予WebRTC权限),在 start() 中创建
        self._context: BrowserContext = None
        # 截图保存目录(相对于当前工作目录)
        self._screenshot_dir = "screenshots"

    def start(self) -> bool:
        """
        启动浏览器
        需求: 启动 Playwright 和 Chromium 浏览器,创建浏览器上下文
        预期结果: 浏览器启动成功,返回 True;失败返回 False
        处理逻辑:
          1. 启动 playwright 实例
          2. 启动 chromium 浏览器(支持慢动作)
          3. 创建浏览器上下文,授予摄像头/麦克风权限(否则 JsSIP 无法建立 WebRTC 连接)
          4. 设置默认视口大小
        注意: 必须授予摄像头/麦克风权限,否则 JsSIP 无法建立 WebRTC 连接
        """
        try:
            # 启动 Playwright 驱动
            self._playwright = sync_playwright().start()
            # 启用 WebRTC 相关参数,允许 localhost 使用媒体设备
            launch_args = [
                "--use-fake-ui-for-media-stream",  # 自动接受媒体流权限提示
                "--autoplay-policy=no-user-gesture-required",  # 允许自动播放音频(振铃音)
                # 无头模式下提供假的音频/视频流,否则 WebRTC 无法建立媒体通道
                # 需求: headless Chromium 没有真实音频设备,必须使用 fake device 才能进行 WebRTC 通话
                "--use-fake-device-for-media-stream",
                # 允许 WebRTC 使用不安全的 ICE 候选(便于本地测试)
                "--allow-running-insecure-content",
            ]
            # AI 对话等场景: 假麦克风循环播放指定 WAV(Chrome 循环读取文件), 使坐席上行
            # 音频持续包含目标语音, 供 FS fork 采集后 ASR 识别命中中断词
            if self.fake_audio_wav:
                launch_args.append("--use-file-for-fake-audio-capture=%s" % self.fake_audio_wav)
            # 启动 Chromium 浏览器,headless 控制是否显示窗口,slow_mo 让操作可见
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo,
                args=launch_args,
            )
            # 创建浏览器上下文,显式授予摄像头和麦克风权限
            # 权限通过 permissions 参数授予,避免页面弹出权限请求弹窗
            self._context = self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                permissions=["camera", "microphone"],
            )
            # 设置默认导航超时时间(30秒)
            self._context.set_default_timeout(30000)
            return True
        except Exception as e:
            print(f"浏览器启动失败: {e}")
            return False

    def stop(self):
        """
        关闭浏览器和playwright
        需求: 释放浏览器资源,关闭所有页面和浏览器进程
        处理逻辑: 按顺序关闭额外上下文、默认上下文、浏览器、playwright 实例
        """
        # 先关闭额外创建的浏览器上下文(坐席B/C等)
        if hasattr(self, '_extra_contexts'):
            for ctx in self._extra_contexts:
                try:
                    ctx.close()
                except Exception:
                    pass
            self._extra_contexts = []
        # 按资源持有顺序逆序释放,避免资源泄漏
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def new_page(self) -> Page:
        """
        创建新页面(用于多坐席并行操作)
        需求: 在当前浏览器上下文中创建一个新的页面
        预期结果: 返回新的 Page 对象,可用于多坐席并行测试
        处理逻辑: 调用上下文的 new_page 方法创建页面
        """
        return self._context.new_page()

    def new_context_page(self) -> Page:
        """
        创建新浏览器上下文和页面(用于不同账号的多坐席操作)
        需求: 创建独立的浏览器上下文,使不同坐席可以使用不同账号登录
        预期结果: 返回新的 Page 对象,拥有独立的 localStorage 和 session
        处理逻辑:
          1. 创建新的浏览器上下文,授予摄像头/麦克风权限
          2. 设置默认超时时间
          3. 创建新页面并返回
        注意: 不同坐席需要不同账号登录时必须使用独立上下文,
              因为同一上下文的页面共享 localStorage 中的登录 token
        """
        context = self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            permissions=["camera", "microphone"],
        )
        context.set_default_timeout(30000)
        # 保存上下文引用以便后续清理
        if not hasattr(self, '_extra_contexts'):
            self._extra_contexts = []
        self._extra_contexts.append(context)
        return context.new_page()

    def navigate_to_login(self, page: Page, url: str = LOCAL_FRONTEND_URL):
        """
        导航到登录页面
        需求: 打开前端 Vue 服务地址,等待页面加载完成
        预期结果: 页面加载完成,登录表单可见 或 已登录状态(软电话组件存在)
        :param page: Page 对象
        :param url: 前端地址(默认从config.py读取LOCAL_FRONTEND_URL)
        处理逻辑:
          1. 访问指定 url(使用 domcontentloaded 避免 networkidle 在 WebSocket 长连接场景下超时)
          2. 轮询检测登录表单可见 或 已登录状态(软电话组件存在),超时 30s
        注意:
          - 同一浏览器上下文中多个页面共享 localStorage,已登录的页面不会显示登录表单
          - 不使用 wait_until="networkidle",因为前端建立 WebSocket 长连接后,
            Playwright 的 networkidle 状态可能无法达到(WebSocket 持续保持连接),
            导致 page.goto 超时。改用 domcontentloaded + 轮询检测元素的方式更可靠。
          - Vue Router 初始跳转有延迟:页面加载后 URL 可能短暂为根路径 '/',
            随后才跳转到 '/login?redirect=/index'。若在跳转前检测 URL 会误判为"已登录",
            因此优先检测页面元素(登录表单/软电话组件),仅当元素稳定出现时才返回,
            避免依赖 URL 判断导致时序竞态问题。
        """
        # 访问前端地址,wait_until="domcontentloaded" 仅等待 DOM 解析完成,
        # 避免在 WebSocket 长连接场景下 networkidle 永远无法达到的问题
        page.goto(url, wait_until="domcontentloaded")
        # 轮询等待登录表单容器出现,或检测到已登录状态(软电话组件存在)
        # 优先检测页面元素,避免 Vue Router 初始跳转延迟导致 URL 误判
        start_time = time.time()
        while time.time() - start_time < 30:
            # 优先检测登录表单(未登录状态)
            login_form = page.query_selector(".login-form")
            if login_form and login_form.is_visible():
                return  # 登录表单可见,正常流程
            # 检测软电话组件(已登录状态)
            softphone = page.query_selector(".soft-phone-bar")
            if softphone:
                return  # 已登录状态,软电话组件存在,跳过登录
            time.sleep(0.5)
        # 超时仍未出现登录表单或软电话组件,最后尝试等待登录表单
        # 此时 Vue Router 应已完成跳转
        try:
            page.wait_for_selector(".login-form", timeout=5000)
        except Exception:
            # 登录表单仍未出现,检查 URL 是否已离开 /login(可能已登录)
            current_url = page.url
            if "/login" not in current_url:
                return  # URL已离开/login,认为已登录
            raise  # 否则抛出超时异常

    def login(self, page: Page, username: str, password: str) -> bool:
        """
        登录系统
        需求: 使用指定账号密码登录系统,登录成功后跳转到管理后台首页
        预期结果: 登录成功返回 True,失败返回 False
        :param page: Page 对象
        :param username: 用户名
        :param password: 密码
        处理逻辑:
          1. 检查是否已登录(同一浏览器上下文中可能已登录),已登录则直接返回 True
          2. 等待用户名输入框可见(placeholder 包含"用户名")
          3. 填写用户名
          4. 等待密码输入框可见(placeholder 包含"密码")
          5. 填写密码
          6. 点击登录按钮(文本"登录")
          7. 等待跳转完成(URL 变化或首页元素出现)
        """
        try:
            # 检查是否已登录(同一浏览器上下文中可能已登录)
            # 如果软电话组件已存在,说明当前页面已处于登录状态
            current_url = page.url
            print(f"[login][当前URL: {current_url}]")
            # 登录表单可见即未登录: Vue Router 跳转 /login 存在时序竞态(run8 实测
            # 登录表单渲染时 URL 仍为根路径 /), 若仅用 URL 判断会误判"已登录",
            # 故元素判断优先, 直接走登录表单流程
            login_form_el = page.query_selector(".login-form")
            if login_form_el and login_form_el.is_visible():
                print("[login][登录表单可见,直接走登录流程]")
            elif self.is_logged_in(page):
                # is_logged_in 返回 True 可能基于 URL 判断,但 SoftPhone 组件可能还未渲染
                # 等待 SoftPhone 组件渲染完成,确保后续签入操作能找到签入按钮
                print(f"[login][is_logged_in=True,等待SoftPhone组件渲染]")
                try:
                    page.wait_for_selector(".soft-phone-bar", timeout=15000)
                    print(f"[login][SoftPhone组件已渲染,确认已登录]")
                except Exception:
                    # SoftPhone 组件未渲染,可能 URL 误判或 token 过期
                    # 检查是否在登录页,如果是则走登录流程
                    if "/login" in page.url:
                        print(f"[login][SoftPhone未渲染且URL在/login,走登录流程]")
                    else:
                        print(f"[login][SoftPhone未渲染但URL不在/login,认为已登录]")
                        return True
                else:
                    return True

            # 如果URL已离开/login但is_logged_in返回False,可能是软电话组件未渲染
            # 此时实际已登录,但需等待 SoftPhone 组件渲染完成,避免后续签入操作失败
            if "/login" not in current_url and current_url != "about:blank":
                print(f"[login][URL已离开/login,等待SoftPhone组件渲染]")
                try:
                    page.wait_for_selector(".soft-phone-bar", timeout=15000)
                    print(f"[login][SoftPhone组件已渲染,认为已登录]")
                except Exception:
                    print(f"[login][SoftPhone组件未渲染,但URL已离开/login,认为已登录]")
                return True

            print(f"[login][未登录,开始填写登录表单]")

            # 等待用户名输入框可见,placeholder 文本因国际化可能不同,使用包含"用户名"的模糊匹配
            username_input = page.wait_for_selector(
                "input[placeholder*='用户名'], input[placeholder*='sername']",
                timeout=15000,
            )
            # 清空并填写用户名
            username_input.fill(username)

            # 等待密码输入框可见
            password_input = page.wait_for_selector(
                "input[type='password'][placeholder*='密码'], input[type='password'][placeholder*='assword']",
                timeout=10000,
            )
            # 填写密码
            password_input.fill(password)

            # 点击登录按钮:XButton 渲染为 button,通过文本"登录"定位
            # 使用 text= 选择器精确匹配按钮文本
            login_button = page.wait_for_selector("button:has-text('登录')", timeout=10000)
            login_button.click()

            # 等待登录完成:URL 离开 /login 页面,或软电话组件出现
            # 使用 expect 风格的轮询等待,最长等待 90 秒
            # 注意:某些情况下 Vue Router 可能不更新 URL(如 hash 模式或路由守卫问题),
            # 因此除了检查 URL 外,还检查软电话组件是否出现作为登录成功的标志
            # 超时从 30 秒调整为 90 秒:远程数据库(<云数据库域名>)网络延迟较高,
            # dict-data/simple-list 等接口可能耗时 13-21 秒,原 30 秒超时不足
            start_time = time.time()
            while time.time() - start_time < 90:
                current_url = page.url
                # 条件1: URL 离开 /login 页面
                if "/login" not in current_url:
                    # 额外等待页面主体加载完成
                    # 使用 domcontentloaded 而非 networkidle,避免 WebSocket 长连接导致 networkidle 无法达到
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    return True
                # 条件2: 软电话组件已渲染(登录成功后底部状态栏会渲染 SoftPhone)
                # 即使 URL 未跳转,软电话组件存在也说明登录已成功
                softphone = page.query_selector(".soft-phone-bar")
                if softphone:
                    # 等待 DOM 加载完成,确保页面资源加载完成
                    # 使用 domcontentloaded 而非 networkidle,避免 WebSocket 长连接导致超时
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                    except Exception:
                        pass  # 加载状态等待失败不影响登录成功的判断
                    return True
                time.sleep(0.5)
            # 超时仍未跳转,登录失败
            return False
        except Exception as e:
            print(f"登录失败: {e}")
            return False

    def is_logged_in(self, page: Page) -> bool:
        """
        检查是否已登录
        需求: 判断当前页面是否处于已登录状态
        预期结果: 已登录返回 True,未登录返回 False
        :return: 已登录返回 True
        处理逻辑: 检查 URL 不是登录页 或 页面中存在软电话组件
        注意: 由于 Vue Router 可能不更新 URL,需要同时检查软电话组件是否存在
        """
        try:
            current_url = page.url
            # URL 不包含 /login 说明已登录
            if "/login" not in current_url:
                return True
            # 即使 URL 仍在 /login,检查软电话组件是否存在
            # 登录成功后底部状态栏会渲染 SoftPhone
            softphone = page.query_selector(".soft-phone-bar")
            return softphone is not None
        except Exception:
            return False

    def open_softphone_panel(self, page: Page) -> bool:
        """
        打开软电话拨号面板(点击拨号按钮)
        需求: 点击软电话栏的拨号按钮,打开拨号弹窗
        预期结果: 拨号弹窗(.popover)可见,返回 True;失败返回 False
        :return: 成功打开返回 True
        处理逻辑:
          1. 等待拨号按钮(.bar-dial 内的 button)可见
          2. 点击拨号按钮
          3. 等待拨号弹窗(.popover)可见
          4. 失败时导航回工作台(/index)重试一次——场景切换后页面可能停留在
             非工作台路由(如外呼任务列表页),SoftPhone 组件不渲染导致拨号按钮不存在
        """
        for attempt in range(2):
            try:
                # 定位拨号按钮:.bar-dial 区域内的按钮(电话图标)
                dial_button = page.wait_for_selector(".bar-dial button", timeout=10000)
                dial_button.click()
                # 等待拨号弹窗出现
                page.wait_for_selector(".popover", timeout=5000)
                return True
            except Exception as e:
                if attempt == 0 and "/index" not in page.url:
                    print(f"打开拨号面板失败(第1次), 导航回工作台重试: {e}")
                    try:
                        page.goto(page.url.split("/cc/")[0] + "/index", wait_until="domcontentloaded")
                        time.sleep(2)
                    except Exception as nav_e:  # noqa: BLE001
                        print(f"导航工作台失败: {nav_e}")
                else:
                    print(f"打开拨号面板失败: {e}")
                    return False
        return False

    def signin(self, page: Page) -> bool:
        """
        SIP签入(点击头像按钮触发REGISTER)
        需求: 点击软电话栏的头像按钮,触发 SIP REGISTER 注册流程
        预期结果: 签入成功返回 True,失败返回 False
        :return: 签入成功返回 True
        处理逻辑:
          1. 检查是否已签入,已签入则直接返回 True
          2. 等待 SoftPhone 组件渲染完成(.soft-phone-bar 出现)
          3. 点击 .bar-auth 按钮(头像图标)
          4. 等待 .switch-wrap 出现(表示已签入,UI 切换到就绪/忙碌开关)
          5. 验证 .offline-tag 消失(离线标签不再显示)
        注意: SIP 注册是异步过程,需要等待后端响应和 JsSIP 注册完成
        """
        try:
            # 检查是否已签入(同一浏览器上下文中可能已签入)
            if self.is_online(page):
                return True

            # 等待 SoftPhone 组件渲染完成
            # 登录成功后页面跳转,SoftPhone 组件可能需要时间异步加载和渲染
            # 如果不等待直接查找 .bar-auth button,可能因组件未渲染而超时
            page.wait_for_selector(".soft-phone-bar", timeout=15000)

            # 定位签入按钮:.bar-auth 区域内的按钮(头像图标)
            signin_button = page.wait_for_selector(".bar-auth button", timeout=10000)
            signin_button.click()
            # 等待签入成功:.switch-wrap 出现表示 REGISTER 已完成
            # 前端修复后 .switch-wrap 只在 registered 事件回调中才显示,确保 UI 状态与实际注册状态同步
            # timeout=30秒: STUN 超时兜底 10秒 + WebSocket 连接 + 401挑战 + REGISTER 约 5-10秒
            page.wait_for_selector(".switch-wrap", timeout=30000)
            # 验证离线标签已消失
            page.wait_for_selector(".offline-tag", state="hidden", timeout=5000)
            return True
        except Exception as e:
            print(f"SIP签入失败: {e}")
            return False

    def signout(self, page: Page) -> bool:
        """
        SIP签出
        需求: 点击头像按钮触发 SIP 取消注册,签出系统
        预期结果: 签出成功返回 True,失败返回 False
        :return: 签出成功返回 True
        处理逻辑:
          1. 点击 .bar-auth 按钮(头像图标,已签入状态下点击会签出)
          2. 等待 .offline-tag 出现(表示已签出)
          3. 验证 .switch-wrap 消失
        """
        try:
            # 定位签出按钮:已签入状态下,.bar-auth 按钮变为 primary 类型
            signout_button = page.wait_for_selector(".bar-auth button", timeout=10000)
            signout_button.click()
            # 等待离线标签出现,表示签出成功
            page.wait_for_selector(".offline-tag", timeout=10000)
            # 验证就绪/忙碌开关消失
            page.wait_for_selector(".switch-wrap", state="hidden", timeout=5000)
            return True
        except Exception as e:
            print(f"SIP签出失败: {e}")
            return False

    def is_online(self, page: Page) -> bool:
        """
        检查是否已签入
        需求: 判断软电话是否处于已签入(在线)状态
        预期结果: 已签入返回 True,未签入返回 False
        :return: 已签入返回 True
        处理逻辑: 检查 .switch-wrap 存在且 .offline-tag 不存在
        """
        try:
            # .switch-wrap 存在表示已签入
            switch_wrap = page.query_selector(".switch-wrap")
            # .offline-tag 不存在表示非离线
            offline_tag = page.query_selector(".offline-tag")
            return switch_wrap is not None and offline_tag is None
        except Exception:
            return False

    def set_ready(self, page: Page, ready: bool = True, max_retries: int = 3) -> bool:
        """
        设置就绪/忙碌状态
        需求: 通过切换 el-switch 设置坐席状态为就绪或忙碌
        预期结果: 设置成功返回 True,失败返回 False
        :param ready: True 设置为就绪,False 设置为忙碌
        :param max_retries: 最大重试次数(签入后 SIP 注册可能需要时间,首次切换可能失败)
        :return: 设置成功返回 True
        处理逻辑:
          1. 检查当前状态(就绪/忙碌)
          2. 如需切换则点击 el-switch 开关
          3. 等待状态标签文本更新
          4. 如果失败则重试(SIP 注册异步完成可能导致状态被重置)
        """
        target_class = ".switch-label--ready" if ready else ".switch-label--busy"
        for attempt in range(1, max_retries + 1):
            try:
                # 签入后 SIP 注册是异步过程,首次切换可能因注册未完成而被后端重置
                # 每次重试前等待更长时间,给 SIP 注册留出足够时间
                wait_sec = 2 * attempt
                time.sleep(wait_sec)
                # 检查当前状态
                current_ready = self.is_ready(page)
                if current_ready == ready:
                    return True
                # 需要切换状态:点击 el-switch 开关
                switch = page.wait_for_selector(".switch-wrap .el-switch", timeout=10000)
                switch.wait_for_element_state("stable", timeout=5000)
                switch.click()
                # 等待状态标签更新
                page.wait_for_selector(target_class, timeout=10000)
                return True
            except Exception as e:
                print(f"设置就绪状态失败(第{attempt}次): {e}")
                if attempt < max_retries:
                    # 重试前检查是否已经是目标状态(可能后端异步推送已完成状态变更)
                    time.sleep(1)
                    if self.is_ready(page) == ready:
                        return True
                    continue
                return False
        return False

    def is_ready(self, page: Page) -> bool:
        """
        检查是否就绪状态
        需求: 判断坐席是否处于就绪状态(可接听来电)
        预期结果: 就绪返回 True,忙碌或离线返回 False
        :return: 就绪返回 True
        处理逻辑: 检查 .switch-label--ready 元素存在
        """
        try:
            # .switch-label--ready 存在表示就绪状态
            ready_label = page.query_selector(".switch-label--ready")
            return ready_label is not None
        except Exception:
            return False

    def make_call(self, page: Page, number: str, gateway_name: str = None) -> bool:
        """
        发起呼叫
        需求: 通过拨号面板输入号码并发起呼叫
        预期结果: 呼叫发起成功,通话弹窗出现,返回 True;失败返回 False
        :param page: Page 对象
        :param number: 被叫号码
        :param gateway_name: 网关名称(可选,仅外呼时使用;为 None 表示内部呼叫,不选网关直接拨打)
        :return: 呼叫发起成功返回 True
        处理逻辑:
          1. 打开拨号面板
          2. 选择呼叫类型(前端 el-radio-button 切换):
             - gateway_name 为 None: 切换到"内部呼叫"(callType=1), 前端隐藏网关下拉框,直接拨打内线
             - gateway_name 指定: 切换到"外呼"(callType=0), 选择对应网关(非必填)
          3. 填写号码到 .dial-input
          4. 点击"拨打"按钮
          5. 等待通话弹窗出现(.active-call)
        前端设计说明(与后端改造对齐):
          - 内部呼叫: 坐席均注册在 sipproxy 上,originate 目标直接用 cc.sip-proxy.public-ip,不走数据库网关
          - 外呼: 通过指定网关出局,携带 X-Gateway-Id 头
        """
        try:
            # 步骤1:打开拨号面板
            if not self.open_softphone_panel(page):
                return False

            # 步骤2:选择呼叫类型
            # 前端 el-radio-group 提供"外呼"(value=0)和"内部呼叫"(value=1)两个 el-radio-button
            # 内部呼叫(callType=1): 隐藏网关下拉框,不携带网关ID,直接拨打内线
            # 外呼(callType=0): 显示网关下拉框(非必填),可选网关
            if gateway_name:
                # 外呼模式: 切换到"外呼"并选择网关
                page.click("label.el-radio-button:has-text('外呼')")
                # 等待网关下拉框加载完成(前端 loadGatewayList 在 SIP 注册成功后异步加载)
                select_trigger = page.wait_for_selector(
                    ".popover .el-select .el-select__wrapper, .popover .el-select .el-input__inner",
                    timeout=10000,
                )
                select_trigger.click()
                # el-option 渲染为 li.el-select-dropdown__item
                option = page.wait_for_selector(
                    f".el-select-dropdown__item:has-text('{gateway_name}')",
                    timeout=5000,
                )
                option.click()
            else:
                # 内部呼叫模式: 切换到"内部呼叫",不选网关(前端会隐藏网关下拉框)
                page.click("label.el-radio-button:has-text('内部呼叫')")

            # 步骤3:填写被叫号码到拨号输入框
            dial_input = page.wait_for_selector(".dial-input", timeout=5000)
            dial_input.fill("")
            dial_input.type(number, delay=50)

            # 步骤4:点击"拨打"按钮
            call_button = page.wait_for_selector(".dialpad-act--primary", timeout=5000)
            call_button.click()

            # 步骤5:等待通话弹窗出现(.active-call)
            # 呼叫建立需要时间(振铃-接听-确认),设置较长超时
            page.wait_for_selector(".active-call", timeout=60000)
            return True
        except Exception as e:
            print(f"发起呼叫失败: {e}")
            return False

    def answer_call(self, page: Page) -> bool:
        """
        接听来电
        需求: 当有来电时,点击接听按钮接通通话
        预期结果: 接听成功,通话建立,返回 True;失败返回 False
        处理逻辑:
          1. 等待 .incoming-dialog 出现(来电弹窗)
          2. 点击 .incoming-btn--accept(接听按钮)
          3. 等待 .incoming-dialog 消失(接听成功)
        注意: 不能因 .active-call 已存在而跳过接听——前端 isInCall 由 sessions.size 控制,
              来电振铃时 .active-call 弹窗也会显示,但 JsSIP 尚未 answer(),必须点击接听按钮。
        """
        try:
            # 等待来电弹窗出现
            page.wait_for_selector(".incoming-dialog", timeout=30000)
            # 点击接听按钮
            accept_button = page.wait_for_selector(".incoming-btn--accept", timeout=5000)
            accept_button.click()
            # 等待来电弹窗消失(handleAnswer 同步清除 incomingCallFlag)
            page.wait_for_selector(".incoming-dialog", state="hidden", timeout=30000)
            return True
        except Exception as e:
            print(f"接听来电失败: {e}")
            return False

    def hangup(self, page: Page) -> bool:
        """
        挂断通话
        需求: 挂断当前活跃通话
        预期结果: 挂断成功,通话弹窗消失,返回 True;失败返回 False
        :return: 挂断成功返回 True
        处理逻辑:
          1. 使用 page.click() 而非 wait_for_selector().click(),避免 Vue 重渲染导致
             ElementHandle 在 click 前已 detach(报 "Element is not attached to the DOM")
          2. 等待 .active-call 消失(通话已结束)
        异常场景: 点击超时(元素被遮挡/不存在)时输出 DOM 诊断信息,便于定位是
                  UI 布局遮挡还是会话状态异常导致按钮缺失
        """
        try:
            # 点击挂断按钮(page.click 会重新定位元素,避免 stale handle)
            page.click(".hangup-full", timeout=5000)
            # 等待通话弹窗消失
            page.wait_for_selector(".active-call", state="hidden", timeout=15000)
            return True
        except Exception as e:
            print(f"挂断通话失败: {e}")
            self._dump_hangup_dom(page)
            return False

    def _dump_hangup_dom(self, page: Page):
        """
        挂断失败时输出软电话 DOM 诊断信息

        需求: 挂断按钮点击失败时,采集页面关键元素状态(存在性/可见性/坐标/遮挡),
              用于区分"按钮被覆盖"与"会话状态异常导致按钮缺失"两类根因
        预期结果: 诊断信息打印到 stdout(被测试日志捕获)
        处理逻辑:
          1. 对软电话关键选择器逐一采集 rect/可见性/z-index
          2. 取 .hangup-full 中心点做 elementFromPoint 命中检测,判断遮挡元素
          3. 统计会话列表数量与 WebRTC 连接状态,反映 JsSIP 会话数
        """
        try:
            diag_js = """(() => {
              const pick = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return { exists: false };
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return {
                  exists: true,
                  visible: st.display !== 'none' && st.visibility !== 'hidden'
                             && r.width > 0 && r.height > 0,
                  rect: { x: Math.round(r.x), y: Math.round(r.y),
                          w: Math.round(r.width), h: Math.round(r.height) },
                  zIndex: st.zIndex, position: st.position
                };
              };
              const btn = pick('.hangup-full');
              let coveredBy = null;
              if (btn.exists && btn.rect && btn.rect.w > 0) {
                const cx = btn.rect.x + btn.rect.w / 2;
                const cy = btn.rect.y + btn.rect.h / 2;
                const hit = document.elementFromPoint(cx, cy);
                coveredBy = hit ? (hit.className || hit.tagName) : 'null';
                const wrap = hit && hit.closest
                  ? hit.closest('.popover,.transfer-panel,.incoming-overlay,.session-list,'
                                + '.dialpad-grid,.el-message,.el-overlay,.el-message-box')
                  : null;
                if (wrap) coveredBy += ' <- ' + wrap.className;
              }
              const pcs = window.__MEDIA_DEBUG_PC__
                ? { hasPc: true, pcState: window.__MEDIA_DEBUG_PC__.connectionState }
                : { hasPc: false };
              return {
                popover: pick('.popover'),
                activeCall: pick('.active-call'),
                hangupFull: btn,
                transferPanel: pick('.transfer-panel'),
                incomingOverlay: pick('.incoming-overlay'),
                sessionList: pick('.session-list'),
                sessionItemCount: document.querySelectorAll('.session-item').length,
                coveredBy: coveredBy,
                debugPc: pcs
              };
            })()"""
            diag = page.evaluate(diag_js)
            print(f"[hangup诊断] DOM状态: {diag}")
        except Exception as de:
            print(f"[hangup诊断] 采集失败: {de}")

    def reject_call(self, page: Page) -> bool:
        """
        拒接来电
        需求: 当有来电时,点击拒接按钮拒绝来电
        预期结果: 拒接成功,来电弹窗消失,返回 True;失败返回 False
        :return: 拒接成功返回 True
        处理逻辑:
          1. 等待 .incoming-dialog 出现
          2. 点击 .incoming-btn--reject(拒接按钮)
          3. 等待 .incoming-dialog 消失
        """
        try:
            # 等待来电弹窗出现
            page.wait_for_selector(".incoming-dialog", timeout=10000)
            # 点击拒接按钮(来电弹窗中的"挂断"按钮)
            reject_button = page.wait_for_selector(".incoming-btn--reject", timeout=5000)
            reject_button.click()
            # 等待来电弹窗消失
            page.wait_for_selector(".incoming-dialog", state="hidden", timeout=10000)
            return True
        except Exception as e:
            print(f"拒接来电失败: {e}")
            return False

    def toggle_hold(self, page: Page) -> bool:
        """
        切换保持/恢复
        需求: 切换当前通话的保持状态(保持->恢复,或恢复->保持)
        预期结果: 操作成功返回 True,失败返回 False
        :return: 操作成功返回 True
        处理逻辑:
          1. 注册console消息收集器,捕获JsSIP的调试输出
          2. 点击 .call-ctrl-btn(文本"保持"或"恢复")
          3. 等待2秒让re-INVITE信令往返
          4. 输出捕获的控制台日志,便于排查re-INVITE未发送问题
        """
        # 控制台消息收集列表,用于捕获JsSIP的调试输出
        console_messages = []

        def on_console_msg(msg):
            # 收集所有控制台消息(log/warning/error)
            console_messages.append(f"[{msg.type}] {msg.text}")

        try:
            # 注册控制台消息监听器
            page.on("console", on_console_msg)

            # 定位保持/恢复按钮:文本为"保持"或"恢复"
            hold_button = page.wait_for_selector(
                ".call-ctrl-btn:has-text('保持'), .call-ctrl-btn:has-text('恢复')",
                timeout=5000,
            )
            hold_button.click()
            # 等待re-INVITE信令往返和UI更新(延长到5秒: 覆盖 hold 媒体协商失败→JsSIP 自发 BYE 的窗口,
            # 便于完整捕获 console 中 re-INVITE 协商/terminate 过程)
            time.sleep(5)
            return True
        except Exception as e:
            print(f"切换保持状态失败: {e}")
            return False
        finally:
            # 输出捕获的控制台消息,便于排查问题
            if console_messages:
                print(f"[toggle_hold] 控制台消息({len(console_messages)}条):")
                for msg in console_messages:
                    print(f"  {msg}")
            else:
                print("[toggle_hold] 未捕获到任何控制台消息(可能toggleHold未被调用)")
            # 移除监听器避免重复
            try:
                page.remove_listener("console", on_console_msg)
            except Exception:
                pass

    def is_held(self, page: Page) -> bool:
        """
        检查是否保持状态
        需求: 判断当前通话是否处于保持状态
        预期结果: 保持中返回 True,否则返回 False
        :return: 保持中返回 True
        处理逻辑: 检查保持按钮是否有 .call-ctrl-btn--active 类,或文本为"恢复"
        """
        try:
            # 保持状态下,保持按钮会添加 --active 类,且文本变为"恢复"
            active_hold = page.query_selector(".call-ctrl-btn--active:has-text('恢复')")
            return active_hold is not None
        except Exception:
            return False

    def toggle_mute(self, page: Page) -> bool:
        """
        切换静音
        需求: 切换当前通话的静音状态(静音->取消静音,或取消静音->静音)
        预期结果: 操作成功返回 True,失败返回 False
        :return: 操作成功返回 True
        处理逻辑: 点击 .call-ctrl-btn(文本"静音"或"取消静音")
        """
        try:
            # 定位静音/取消静音按钮:文本为"静音"或"取消静音"
            mute_button = page.wait_for_selector(
                ".call-ctrl-btn:has-text('静音'), .call-ctrl-btn:has-text('取消静音')",
                timeout=5000,
            )
            mute_button.click()
            # 等待按钮状态切换
            time.sleep(1)
            return True
        except Exception as e:
            print(f"切换静音状态失败: {e}")
            return False

    def is_muted(self, page: Page) -> bool:
        """
        检查是否静音状态
        需求: 判断当前通话是否处于静音状态
        预期结果: 静音中返回 True,否则返回 False
        :return: 静音中返回 True
        处理逻辑: 检查静音按钮是否有 .call-ctrl-btn--active 类,或文本为"取消静音"
        """
        try:
            # 静音状态下,静音按钮会添加 --active 类,且文本变为"取消静音"
            active_mute = page.query_selector(".call-ctrl-btn--active:has-text('取消静音')")
            return active_mute is not None
        except Exception:
            return False

    def send_dtmf(self, page: Page, key: str) -> bool:
        """
        发送DTMF按键
        需求: 在通话中发送 DTMF 双音多频信号
        预期结果: 发送成功返回 True,失败返回 False
        :param key: 按键(0-9,*,#)
        :return: 成功返回 True
        处理逻辑: 点击通话中拨号盘(.dialpad-key--incall)对应按键
        """
        try:
            # 验证按键合法性
            valid_keys = set("0123456789*#")
            if key not in valid_keys:
                print(f"无效的DTMF按键: {key}")
                return False
            # 定位通话中拨号盘的对应按键
            # 使用 has-text 精确匹配按键文本
            dtmf_button = page.wait_for_selector(
                f".dialpad-key--incall:has-text('{key}')",
                timeout=5000,
            )
            dtmf_button.click()
            return True
        except Exception as e:
            print(f"发送DTMF按键失败: {e}")
            return False

    def get_active_call_number(self, page: Page) -> str:
        """
        获取当前通话的对方号码
        需求: 获取当前焦点通话的对方号码
        预期结果: 返回号码字符串,无通话返回空字符串
        :return: 号码字符串,无通话返回空
        处理逻辑: 读取 .active-call-number 元素的文本内容
        """
        try:
            number_element = page.query_selector(".active-call-number")
            if number_element:
                return number_element.inner_text().strip()
            return ""
        except Exception:
            return ""

    def get_call_duration(self, page: Page) -> str:
        """
        获取当前通话时长
        需求: 获取当前焦点通话的已通话时长
        预期结果: 返回时长字符串(如"00:00:05"),无通话返回空字符串
        :return: 时长字符串(如"00:00:05"),无通话返回空
        处理逻辑: 读取 .active-call-timer 元素的文本内容
        """
        try:
            timer_element = page.query_selector(".active-call-timer")
            if timer_element:
                return timer_element.inner_text().strip()
            return ""
        except Exception:
            return ""

    def get_session_count(self, page: Page) -> int:
        """
        获取当前会话数量(多通话场景)
        需求: 统计当前软电话中的通话会话数量
        预期结果: 返回会话数量,无通话返回0
        :return: 会话数
        处理逻辑:
          1. 检查是否存在 .session-list(多通话时显示)
          2. 统计 .session-item 数量
          3. 若无 .session-list 但有 .active-call,则为单通话,返回1
        """
        try:
            # 检查是否存在多通话列表
            session_list = page.query_selector(".session-list")
            if session_list:
                # 统计会话项数量
                items = page.query_selector_all(".session-item")
                return len(items)
            # 无多通话列表,检查是否有活跃通话
            active_call = page.query_selector(".active-call")
            if active_call:
                return 1
            return 0
        except Exception:
            return 0

    def switch_session(self, page: Page, call_id: str = None, index: int = 0) -> bool:
        """
        切换活跃会话
        需求: 在多通话场景下,切换操作焦点到指定会话
        预期结果: 切换成功返回 True,失败返回 False
        :param call_id: 会话ID(可选,不传则按index)
        :param index: 会话索引(从0开始)
        :return: 切换成功返回 True
        处理逻辑:
          1. 获取所有会话项 .session-item
          2. 根据 call_id 或 index 选择目标会话
          3. 点击目标会话项切换焦点
        """
        try:
            # 获取所有会话项
            session_items = page.query_selector_all(".session-item")
            if not session_items:
                print("无可用会话")
                return False

            # 确定目标会话项
            if call_id:
                # 按 call_id 查找:会话项的 data 属性或文本匹配
                # 由于 UI 中会话项没有直接暴露 call_id,这里通过 index 切换
                # 实际场景中可根据业务需要扩展
                print(f"按 call_id 切换会话功能需要 UI 支持,当前按 index 切换")
                target_item = session_items[index] if index < len(session_items) else None
            else:
                # 按 index 选择
                if index >= len(session_items):
                    print(f"会话索引 {index} 超出范围(共 {len(session_items)} 个会话)")
                    return False
                target_item = session_items[index]

            if target_item:
                target_item.click()
                # 等待焦点切换完成
                time.sleep(1)
                return True
            return False
        except Exception as e:
            print(f"切换会话失败: {e}")
            return False

    def wait_for_incoming_call(self, page: Page, timeout: int = 30000) -> bool:
        """
        等待来电
        需求: 阻塞等待直到收到来电
        预结果: 收到来电返回 True,超时返回 False
        :param timeout: 超时毫秒
        :return: 收到来电返回 True
        处理逻辑: 等待 .incoming-dialog 元素出现;若通话已建立(.active-call 存在),
                 说明来电已被自动接听或已跳过弹窗阶段,同样视为收到来电
        """
        try:
            start_time = time.time()
            timeout_sec = timeout / 1000
            last_diag = 0
            while time.time() - start_time < timeout_sec:
                # 优先检测来电弹窗
                if page.query_selector(".incoming-dialog"):
                    return True
                # 兜底: 若通话已建立(自动接听/跳过弹窗),也视为收到来电
                if page.query_selector(".active-call"):
                    print("[wait_for_incoming_call] 检测到 .active-call 已存在(可能已自动接听)")
                    return True
                # 每10秒输出一次诊断信息(仅在长等待时)
                now = time.time()
                if now - last_diag > 10:
                    last_diag = now
                    elapsed = int(now - start_time)
                    try:
                        url = page.url
                        has_sp = page.query_selector(".soft-phone-bar") is not None
                        has_sw = page.query_selector(".switch-wrap") is not None
                        has_ic = page.query_selector(".incoming-call") is not None
                        status_text = ""
                        sp_el = page.query_selector(".soft-phone-bar")
                        if sp_el:
                            status_text = sp_el.text_content()[:80] if sp_el.text_content() else "(empty)"
                        print(f"[wait_for_incoming_call] 诊断(t+{elapsed}s): url={url[-60:]}, "
                              f"softphone_bar={has_sp}, switch_wrap={has_sw}, incoming_call={has_ic}, "
                              f"sp_text='{status_text}'")
                    except Exception as diag_e:
                        print(f"[wait_for_incoming_call] 诊断异常: {diag_e}")
                time.sleep(0.3)
            return False
        except Exception:
            return False

    def wait_for_call_connected(self, page: Page, timeout: int = 60000) -> bool:
        """
        等待通话建立
        需求: 阻塞等待直到通话建立(从振铃进入通话中)
        预期结果: 通话建立返回 True,超时返回 False
        :param timeout: 超时毫秒
        :return: 通话建立返回 True
        处理逻辑: 等待 .active-call 元素出现且 .active-call-timer 开始计时(非 00:00:00)
        """
        try:
            # 等待通话弹窗出现
            page.wait_for_selector(".active-call", timeout=timeout)
            # 额外等待计时器开始(通话确认后才开始计时)
            # 计时器初始为 00:00:00,确认后开始递增
            start_time = time.time()
            timeout_sec = timeout / 1000
            while time.time() - start_time < timeout_sec:
                duration = self.get_call_duration(page)
                # 计时器有值且不为初始的 00:00:00 表示通话已确认
                if duration and duration != "00:00:00":
                    return True
                time.sleep(0.5)
            # 即使计时器未更新,只要 .active-call 存在也认为通话已建立
            return page.query_selector(".active-call") is not None
        except Exception:
            return False

    def wait_for_call_ended(self, page: Page, timeout: int = 30000) -> bool:
        """
        等待通话结束
        需求: 阻塞等待直到当前通话结束
        预期结果: 通话结束返回 True,超时返回 False
        :param timeout: 超时毫秒
        :return: 通话结束返回 True
        处理逻辑: 等待 .active-call 元素消失
        """
        try:
            # 等待通话弹窗消失
            page.wait_for_selector(".active-call", state="hidden", timeout=timeout)
            return True
        except Exception:
            return False

    def get_status_text(self, page: Page) -> str:
        """
        获取软电话当前状态文本(用于日志)
        需求: 综合判断软电话当前状态,返回可读的状态描述
        预期结果: 返回状态描述字符串
        :return: 状态描述字符串
        处理逻辑:
          1. 检查是否离线(.offline-tag 存在)
          2. 检查是否通话中(.active-call 存在)
          3. 检查是否保持中(保持按钮 --active)
          4. 检查是否就绪/忙碌(.switch-label--ready/--busy)
          5. 检查是否有来电(.incoming-dialog 存在)
        """
        try:
            # 优先级1:检查是否有来电(来电弹窗优先级最高)
            if page.query_selector(".incoming-dialog"):
                return "来电中"

            # 优先级2:检查是否离线
            if page.query_selector(".offline-tag"):
                return "离线"

            # 优先级3:检查是否通话中
            if page.query_selector(".active-call"):
                # 通话中细分状态:保持/静音/正常通话
                if self.is_held(page):
                    return "通话中(保持)"
                if self.is_muted(page):
                    return "通话中(静音)"
                return "通话中"

            # 优先级4:检查就绪/忙碌状态
            if page.query_selector(".switch-label--ready"):
                return "就绪"
            if page.query_selector(".switch-label--busy"):
                return "忙碌"

            # 默认状态
            return "未知状态"
        except Exception:
            return "状态获取失败"

    def take_screenshot(self, page: Page, name: str):
        """
        截图保存
        需求: 对当前页面截图并保存到 screenshots 目录
        预期结果: 截图文件保存成功
        :param name: 截图名称
        处理逻辑:
          1. 确保 screenshots 目录存在
          2. 生成带时间戳的文件名
          3. 调用 page.screenshot 保存全页面截图
        """
        try:
            # 确保截图目录存在
            if not os.path.exists(self._screenshot_dir):
                os.makedirs(self._screenshot_dir)
            # 生成带时间戳的文件名,避免覆盖
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{self._screenshot_dir}/{name}_{timestamp}.png"
            # 保存全页面截图
            page.screenshot(path=filename, full_page=True)
            print(f"截图已保存: {filename}")
        except Exception as e:
            print(f"截图保存失败: {e}")

    # ==================== 场景6: 咨询转接相关操作 ====================

    def open_transfer_popup(self, page: Page) -> bool:
        """
        打开通话中转接弹窗(点击"转接"按钮)

        需求: 通话中点击转接按钮,打开咨询转接弹窗(.transfer-panel)
        预期结果: .transfer-panel 元素可见,返回 True;失败返回 False
        处理逻辑:
          1. 定位 .call-ctrl-btn--transfer 按钮(转接按钮)
          2. 点击按钮
          3. 等待 .transfer-panel 弹窗可见
        """
        try:
            transfer_btn = page.wait_for_selector(".call-ctrl-btn--transfer", timeout=5000)
            transfer_btn.click()
            page.wait_for_selector(".transfer-panel", timeout=5000)
            return True
        except Exception as e:
            print(f"打开转接弹窗失败: {e}")
            return False

    def perform_transfer(self, page: Page, target: str,
                         transfer_type: str = "attended",
                         gateway_name: str = None) -> bool:
        """
        执行转接操作(填写表单并点击确认转接)

        需求: 在转接弹窗中填写目标号码、选择转接类型、(可选)选择网关,点击确认转接
        预期结果: 转接请求已发送,转接弹窗关闭,返回 True;失败返回 False
        :param page: Page 对象
        :param target: 转接目标号码
        :param transfer_type: 转接类型 attended=咨询转接(默认), blind=盲转
        :param gateway_name: 网关名称(可选,为None不选择网关)
        处理逻辑:
          1. 选择转接类型(el-radio-button)
          2. (可选)选择出局网关
          3. 填写目标号码到 .dial-input
          4. 点击 .dialpad-act--primary(确认转接按钮)
          5. 等待 .transfer-panel 弹窗关闭
        """
        # 注册console消息收集器,捕获JsSIP发送REFER时的调试输出
        console_messages = []

        def on_console_msg(msg):
            console_messages.append(f"[{msg.type}] {msg.text}")

        try:
            page.on("console", on_console_msg)

            # 步骤1: 选择转接类型(attended=咨询转接, blind=盲转)
            # 前端 el-radio-button value="attended"/"blind"
            transfer_label = "咨询转接" if transfer_type == "attended" else "盲转"
            page.click(f"label.el-radio-button:has-text('{transfer_label}')")
            time.sleep(0.5)

            # 步骤2: 选择出局网关(可选)
            if gateway_name:
                # 点击 el-select 触发下拉
                select_trigger = page.query_selector(".transfer-panel .el-select .el-select__wrapper, "
                                                     ".transfer-panel .el-select .el-input__inner")
                if select_trigger:
                    select_trigger.click()
                    option = page.wait_for_selector(
                        f".el-select-dropdown__item:has-text('{gateway_name}')", timeout=5000
                    )
                    option.click()
                    time.sleep(0.3)

            # 步骤3: 填写目标号码到 .dial-input(转接弹窗内的输入框)
            transfer_input = page.wait_for_selector(".transfer-panel .dial-input", timeout=5000)
            transfer_input.fill("")
            transfer_input.type(target, delay=50)

            # 步骤4: 点击确认转接按钮
            confirm_btn = page.wait_for_selector(
                ".transfer-panel .dialpad-act--primary", timeout=5000
            )
            confirm_btn.click()

            # 等待2秒让REFER信令发送并捕获控制台输出
            time.sleep(2)

            # 通过page.evaluate读取window._transferDebug,获取JsSIP refer()的执行结果
            # 这比console消息捕获更可靠,能确认REFER是否真正发送
            try:
                transfer_debug = page.evaluate("window._transferDebug")
                if transfer_debug:
                    print(f"[perform_transfer] window._transferDebug: {transfer_debug}")
                else:
                    print("[perform_transfer] window._transferDebug为空,handleTransfer可能未执行")
            except Exception as eval_e:
                print(f"[perform_transfer] 读取window._transferDebug失败: {eval_e}")

            # 步骤5: 等待转接弹窗关闭(说明请求已发送)
            page.wait_for_selector(".transfer-panel", state="hidden", timeout=10000)
            return True
        except Exception as e:
            print(f"执行转接失败: {e}")
            return False
        finally:
            # 输出捕获的控制台消息,便于排查REFER未发送问题
            if console_messages:
                print(f"[perform_transfer] 控制台消息({len(console_messages)}条):")
                for msg in console_messages:
                    print(f"  {msg}")
            page.remove_listener("console", on_console_msg)

    # ==================== 场景7: 外呼任务页面操作 ====================

    def navigate_to_admin_path(self, page: Page, path: str) -> bool:
        """
        导航到管理后台指定路径

        需求: 在已登录的管理后台页面跳转到指定路由路径
        预期结果: 路由跳转完成,目标页面加载完成
        :param page: Page 对象
        :param path: 路由路径(如 /cc/cc_call/autocall-task,注意要包含完整的菜单层级路径)
        处理逻辑:
          1. 通过Vue Router实例的push方法进行编程式导航(异步等待完成)
          2. 等待目标页面组件渲染完成
          3. 检查是否被重定向到登录页或停留在错误页
        设计说明:
          前端使用 createWebHistory(history模式),动态路由通过 router.addRoute 注册;
          page.goto 会重新加载整个Vue应用,虽然路由守卫会重新生成路由,
          但是异步生成过程中可能短暂显示404;
          history.pushState + popstate 方案不可行,因为 routerHelper.ts 中
          promoteRouteLevel 函数创建了临时的 createWebHashHistory() router 实例,
          该实例未销毁会监听 popstate 事件并在URL后追加 '#/';
          因此通过 Vue Router 实例的 push 方法导航,它能正确匹配动态路由且不重载页面
        异常场景:
          - Vue Router实例获取失败: 返回失败
          - 路由不存在: router.push 会抛出异常,捕获并返回失败
          - 跳转后停留在错误页: 等待组件渲染,超时返回失败
        """
        try:
            current_url = page.url
            # 如果已经在目标路径,直接返回
            if path in current_url and "/login" not in current_url:
                return True

            # 通过Vue Router实例的push方法导航(异步等待完成)
            # Vue Router实例挂在 app.config.globalProperties.$router 上
            # 通过 #__vue_app__ 获取Vue应用实例
            push_result = page.evaluate(
                """async (path) => {
                    try {
                        const app = document.querySelector('#app');
                        if (!app || !app.__vue_app__) {
                            return { ok: false, reason: 'vue_app_not_found' };
                        }
                        const router = app.__vue_app__.config.globalProperties.$router;
                        if (!router) {
                            return { ok: false, reason: 'router_not_found' };
                        }
                        // 检查路由是否存在(避免匹配到404 catch-all路由)
                        const routes = router.getRoutes();
                        const matched = routes.find(r => r.path === path);
                        if (!matched) {
                            // 查找相似路径,便于排查
                            const similar = routes
                                .filter(r => r.path.includes(path.split('/').pop()))
                                .map(r => r.path);
                            return { ok: false, reason: 'route_not_found', similarPaths: similar };
                        }
                        // 异步等待路由跳转完成
                        await router.push(path);
                        return { ok: true, currentPath: router.currentRoute.value.path };
                    } catch (e) {
                        return { ok: false, reason: 'push_error: ' + e.message };
                    }
                }""",
                path,
            )

            if not push_result.get("ok"):
                print(f"[navigate_to_admin_path] router.push失败: {push_result.get('reason')}")
                if push_result.get("similarPaths"):
                    print(f"[navigate_to_admin_path] 相似路径: {push_result.get('similarPaths')}")
                return False

            # 等待Vue Router完成跳转和组件渲染(异步组件加载)
            time.sleep(2)

            # 检查是否被重定向到登录页
            current_url = page.url
            if "/login" in current_url:
                print(f"[navigate_to_admin_path] 被重定向到登录页,URL: {current_url}")
                return False

            # 等待目标页面组件渲染完成(以.el-table或主内容区出现为标志)
            # 外呼任务页面有.el-table,其他页面可能有.el-form
            try:
                page.wait_for_selector(".el-table, .el-form, .el-card", timeout=10000)
            except Exception:
                # 组件可能还在加载,额外等待
                time.sleep(2)

            return True
        except Exception as e:
            print(f"导航到 {path} 失败: {e}")
            return False

    def open_autocall_task_create_form(self, page: Page) -> bool:
        """
        打开外呼任务创建表单(点击"新增任务"按钮)

        需求: 在外呼任务列表页点击"新增任务"按钮,打开创建表单弹窗
        预期结果: 表单弹窗(.com-dialog)可见,返回 True;失败返回 False
        处理逻辑:
          1. 等待页面主容器渲染完成(.el-table 或 .el-form)
          2. 等待"新增任务"按钮可见
          3. 点击按钮
          4. 等待表单弹窗 .com-dialog 可见
        设计说明:
          前端使用自定义 Dialog 组件(对 ElDialog 的封装,额外添加 class="com-dialog"),
          因此使用 .com-dialog 选择器更精确,避免与页面上其他 .el-dialog 冲突
        异常场景:
          - 按钮未渲染: 可能权限不足或页面未加载完成,打印当前URL和按钮数量便于排查
          - 弹窗未出现: 点击可能未生效,返回失败
        """
        try:
            # 先等待页面主容器渲染完成,确保列表已加载
            try:
                page.wait_for_selector(".el-table", timeout=10000)
            except Exception:
                # 表格未出现可能是因为没有数据,继续尝试查找按钮
                pass

            # 打印当前URL和所有可见按钮文本,便于排查
            current_url = page.url
            btn_texts = page.evaluate(
                "() => Array.from(document.querySelectorAll('button')).map(b => b.textContent.trim()).filter(t => t)"
            )
            print(f"[open_autocall_task_create_form] 当前URL: {current_url}")
            print(f"[open_autocall_task_create_form] 页面可见按钮: {btn_texts}")

            # 点击"新增任务"按钮(支持带图标前缀的文本匹配)
            create_btn = page.wait_for_selector("button:has-text('新增任务')", timeout=15000)
            create_btn.click()
            # 等待表单弹窗出现(使用 .com-dialog 选择器,是自定义 Dialog 组件的 class)
            page.wait_for_selector(".com-dialog", timeout=10000)
            # 额外等待弹窗内容渲染完成
            time.sleep(1)
            return True
        except Exception as e:
            print(f"打开外呼任务创建表单失败: {e}")
            return False

    def fill_autocall_task_form(self, page: Page, task_name: str,
                                target_numbers: str,
                                ivr_flow: str = None,
                                gateway_name: str = None,
                                caller_id: str = None) -> bool:
        """
        填写外呼任务表单字段

        需求: 在创建/修改外呼任务表单弹窗中填写任务名称、被叫号码、IVR流程、网关等字段
        预期结果: 表单字段填写完成,返回 True;失败返回 False
        :param page: Page 对象
        :param task_name: 任务名称
        :param target_numbers: 被叫号码列表(逗号分隔)
        :param ivr_flow: IVR流程ID(可选)
        :param gateway_name: 网关名称(可选)
        :param caller_id: 对外主叫号码(可选)
        处理逻辑:
          1. 填写任务名称
          2. 填写被叫号码列表(textarea)
          3. 填写IVR流程ID(可选)
          4. 选择网关(可选)
          5. 填写主叫号码(可选)
        设计说明:
          所有选择器限定在 .com-dialog 弹窗范围内,
          避免与页面搜索表单(也有"任务名称"字段)冲突
        """
        try:
            # 步骤1: 填写任务名称(限定在弹窗内,避免匹配到搜索表单的同名字段)
            # 弹窗 open() 内部 resetForm+异步加载选项会触发 Vue 重渲染,选择器可能短暂脱链,
            # 故用轮询等待替代 wait_for_selector,并在 fill 竞态时自动重试(与 ivr流程测试 策略一致)
            task_name_sel = ".com-dialog .el-form-item:has-text('任务名称') input"
            if not self._wait_visible(page, task_name_sel, timeout=10000):
                print(f"填写外呼任务表单失败: 弹窗内未找到任务名称输入框")
                return False
            for _ in range(3):
                try:
                    page.fill(task_name_sel, task_name)
                    break
                except Exception as fill_exc:
                    if _ == 2:
                        print(f"填写外呼任务表单失败: 任务名称 fill 竞态: {fill_exc}")
                        return False
                    time.sleep(1)

            # 步骤2: 填写被叫号码列表(textarea)
            numbers_sel = ".com-dialog .el-form-item:has-text('被叫号码列表') textarea"
            if not self._wait_visible(page, numbers_sel, timeout=10000):
                print(f"填写外呼任务表单失败: 弹窗内未找到被叫号码列表 textarea")
                return False
            for _ in range(3):
                try:
                    page.fill(numbers_sel, target_numbers)
                    break
                except Exception as fill_exc:
                    if _ == 2:
                        print(f"填写外呼任务表单失败: 被叫号码 fill 竞态: {fill_exc}")
                        return False
                    time.sleep(1)

            # 步骤3: 选择 IVR 流程(可选, 前端为 el-select 下拉, 选项文本匹配)
            if ivr_flow:
                if not self._select_el_option(page, "IVR流程", ivr_flow, timeout=15000):
                    print(f"填写外呼任务表单失败: IVR流程下拉选项未选中: {ivr_flow}")
                    return False

            # 步骤4: 选择网关(可选, el-select 下拉)
            if gateway_name:
                if not self._select_el_option(page, "出局网关", gateway_name, timeout=15000):
                    print(f"填写外呼任务表单失败: 出局网关下拉选项未选中: {gateway_name}")
                    return False

            # 步骤5: 填写主叫号码(可选)
            if caller_id:
                caller_sel = ".com-dialog .el-form-item:has-text('对外主叫号码') input"
                if not self._wait_visible(page, caller_sel, timeout=10000):
                    print(f"填写外呼任务表单失败: 弹窗内未找到对外主叫号码输入框")
                    return False
                page.fill(caller_sel, caller_id)

            return True
        except Exception as e:
            print(f"填写外呼任务表单失败: {e}")
            return False

    def _wait_visible(self, page: Page, selector: str, timeout: int = 10000) -> bool:
        """轮询等待元素可见(规避弹窗 Vue 重渲染导致的 wait_for_selector 短暂失败)"""
        deadline = time.time() + timeout / 1000.0
        while time.time() < deadline:
            try:
                el = page.query_selector(selector)
                if el and el.is_visible():
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _select_el_option(self, page: Page, label: str, option_text: str, timeout: int = 15000) -> bool:
        """在 .com-dialog 内点选指定 label 的 el-select 下拉选项(文本匹配, 含竞态重试)"""
        deadline = time.time() + timeout / 1000.0
        while time.time() < deadline:
            try:
                select_el = page.query_selector(
                    ".com-dialog .el-form-item:has-text('%s') .el-select" % label)
                if select_el:
                    option = self._find_visible_el_option(page, option_text)
                    if not option:
                        select_el.click()
                        time.sleep(0.6)
                        option = self._find_visible_el_option(page, option_text)
                    if option:
                        option.click()
                        time.sleep(0.3)
                        return True
            except Exception as exc:
                print(f"[_select_el_option] {label} 点选竞态重试: {exc}")
            time.sleep(1)
        return False

    def _find_visible_el_option(self, page: Page, option_text: str):
        """找到文本匹配且可见的下拉选项(规避多个隐藏下拉面板干扰)"""
        try:
            for opt in page.query_selector_all(
                    ".el-select-dropdown__item:has-text('%s')" % option_text):
                try:
                    if opt.is_visible():
                        return opt
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def submit_autocall_task_form(self, page: Page) -> bool:
        """
        提交外呼任务表单(点击"确定"按钮)

        需求: 点击表单弹窗的"确定"按钮提交表单,等待弹窗关闭
        预期结果: 表单提交成功,弹窗关闭,返回 True;失败返回 False
        处理逻辑:
          1. 点击弹窗内的"确定"按钮
          2. 等待 .com-dialog 关闭
        设计说明:
          前端按钮文本是"确 定"(中间有空格),Playwright 的 :has-text() 是子字符串匹配,
          使用 '确 定' 能精确匹配;同时限定在 .com-dialog 弹窗范围内,
          避免匹配到页面上其他"确定"按钮(如消息确认弹窗)
        异常场景:
          - 按钮未找到: 弹窗可能未正确打开,返回失败
          - 弹窗未关闭: 提交可能失败(表单校验不通过),返回失败
        """
        try:
            # 点击弹窗内的"确定"按钮(按钮文本是"确 定",带空格)
            submit_btn = page.wait_for_selector(
                ".com-dialog button:has-text('确 定')", timeout=10000
            )
            submit_btn.click()
            # 等待弹窗关闭
            page.wait_for_selector(".com-dialog", state="hidden", timeout=15000)
            return True
        except Exception as e:
            print(f"提交外呼任务表单失败: {e}")
            return False

    def find_autocall_task_row(self, page: Page, task_name: str) -> bool:
        """
        在外呼任务列表中查找指定任务名称的行

        需求: 通过任务名称定位列表中的行,用于后续操作
        :return: 找到返回 True,未找到返回 False
        """
        try:
            row = page.query_selector(f".el-table__row:has-text('{task_name}')")
            return row is not None
        except Exception:
            return False

    def execute_autocall_task_by_name(self, page: Page, task_name: str) -> bool:
        """
        通过任务名称点击"执行"按钮

        需求: 在外呼任务列表中找到指定任务,点击该行的"执行"按钮
        预期结果: 点击成功并触发执行确认弹窗,确认后任务状态变更为"执行中"
        处理逻辑:
          1. 定位包含任务名称的表格行
          2. 在该行内查找"执行"按钮
          3. 点击"执行"按钮
          4. 处理二次确认弹窗(点击"确定"按钮)
        设计说明:
          yudao 框架的 message.confirm 使用 ElMessageBox.confirm,
          确认按钮文本是 t('common.ok') = "确定"(不是"确认"),
          取消按钮文本是 t('common.cancel') = "取消"
        异常场景:
          - 确认弹窗未出现: 可能是任务状态不允许执行,记录警告但视为成功
          - 确认按钮未找到: 弹窗可能使用了不同的文本,尝试备用选择器
        """
        try:
            # 定位包含任务名称的行
            row = page.wait_for_selector(
                f".el-table__row:has-text('{task_name}')", timeout=10000
            )
            # 在该行内查找"执行"按钮并点击
            execute_btn = row.query_selector("button:has-text('执行')")
            if not execute_btn:
                print(f"未找到任务 '{task_name}' 的执行按钮(可能状态非待执行)")
                return False
            execute_btn.click()
            # 处理二次确认弹窗(message-box)
            # yudao 框架的确认按钮文本是 "确定"(t('common.ok')的中文翻译)
            try:
                confirm_btn = page.wait_for_selector(
                    ".el-message-box button:has-text('确定')", timeout=5000
                )
                confirm_btn.click()
                # 等待弹窗关闭
                page.wait_for_selector(".el-message-box", state="hidden", timeout=5000)
            except Exception as e:
                # 确认弹窗可能不存在(直接执行),或已自动关闭
                print(f"[execute_autocall_task] 确认弹窗处理: {e}")
            time.sleep(1)  # 等待状态更新
            return True
        except Exception as e:
            print(f"执行外呼任务失败: {e}")
            return False

    def view_autocall_task_records(self, page: Page, task_name: str) -> bool:
        """
        通过任务名称点击"记录"按钮查看执行记录

        需求: 在外呼任务列表中找到指定任务,点击该行的"记录"按钮,打开任务记录弹窗
        预期结果: 任务记录弹窗打开,返回 True;失败返回 False
        """
        try:
            # 定位包含任务名称的行
            row = page.wait_for_selector(
                f".el-table__row:has-text('{task_name}')", timeout=10000
            )
            # 在该行内查找"记录"按钮并点击
            record_btn = row.query_selector("button:has-text('记录')")
            if not record_btn:
                print(f"未找到任务 '{task_name}' 的记录按钮")
                return False
            record_btn.click()
            # 等待任务记录弹窗打开(使用 .com-dialog 选择器,自定义 Dialog 组件的 class)
            page.wait_for_selector(".com-dialog:has-text('外呼任务执行记录')", timeout=10000)
            return True
        except Exception as e:
            print(f"查看任务记录失败: {e}")
            return False

    def close_dialog(self, page: Page) -> bool:
        """
        关闭当前打开的弹窗

        需求: 关闭 com-dialog 弹窗
        预期结果: 弹窗关闭返回 True
        处理逻辑:
          1. 查找弹窗关闭按钮(Dialog组件使用 ep:close 图标,渲染为 .el-icon 或 i 标签)
          2. 点击关闭按钮
          3. 等待弹窗隐藏
        """
        try:
            # Dialog 组件使用自定义关闭按钮(Icon icon="ep:close"),
            # 渲染为 .el-icon-close 或包含 ep:close 的元素
            close_btn = page.query_selector(".com-dialog .el-icon:has(svg)")
            if not close_btn:
                # 降级使用标准 el-dialog 关闭按钮
                close_btn = page.query_selector(".el-dialog__headerbtn")
            if close_btn:
                close_btn.click()
                page.wait_for_selector(".com-dialog", state="hidden", timeout=5000)
            return True
        except Exception as e:
            print(f"关闭弹窗失败: {e}")
            return False

    def get_autocall_task_status_text(self, page: Page, task_name: str) -> str:
        """
        获取外呼任务的状态文本

        需求: 从列表中查找任务,返回其状态标签文本
        :return: 状态文本(待执行/执行中/已完成/已暂停/已取消),未找到返回空字符串
        """
        try:
            row = page.query_selector(f".el-table__row:has-text('{task_name}')")
            if not row:
                return ""
            tag = row.query_selector(".el-tag")
            if tag:
                return tag.inner_text().strip()
            return ""
        except Exception:
            return ""

    def refresh_autocall_task_list(self, page: Page) -> bool:
        """
        刷新外呼任务列表(等待列表加载)

        需求: 等待外呼任务列表加载完成
        预期结果: 列表加载完成返回 True
        处理逻辑:
          等待 .el-table 加载完成即可,不强制要求有数据行(空列表也是正常状态)
        异常场景:
          - 表格未出现: 页面可能未正确渲染,返回失败
        """
        try:
            # 等待表格容器加载完成(空列表时没有 .el-table__row,但 .el-table 存在)
            page.wait_for_selector(".el-table", timeout=10000)
            return True
        except Exception as e:
            print(f"刷新外呼任务列表失败: {e}")
            return False

    def delete_autocall_task_by_name(self, page: Page, task_name: str) -> bool:
        """
        通过任务名称删除外呼任务(清理测试数据用)

        需求: 删除指定名称的外呼任务,用于测试清理
        预期结果: 删除成功返回 True
        处理逻辑:
          1. 定位任务行
          2. 点击"删除"按钮
          3. 处理二次确认弹窗(点击"确定"按钮)
        设计说明:
          yudao 框架的 message.delConfirm 使用 ElMessageBox.confirm,
          确认按钮文本是 t('common.ok') = "确定"(不是"确认")
        """
        try:
            row = page.query_selector(f".el-table__row:has-text('{task_name}')")
            if not row:
                return True  # 任务不存在视为已删除
            delete_btn = row.query_selector("button:has-text('删除')")
            if not delete_btn:
                return True
            delete_btn.click()
            # 处理二次确认弹窗(确认按钮文本是"确定")
            try:
                confirm_btn = page.wait_for_selector(
                    ".el-message-box button:has-text('确定')", timeout=5000
                )
                confirm_btn.click()
                # 等待弹窗关闭
                page.wait_for_selector(".el-message-box", state="hidden", timeout=5000)
            except Exception:
                pass
            time.sleep(1)
            return True
        except Exception as e:
            print(f"删除外呼任务失败: {e}")
            return False


# ==================== 测试入口(可直接运行) ====================
if __name__ == "__main__":
    """
    简单的冒烟测试:验证浏览器启动、登录、签入等基础流程
    运行方式: python browser_test.py
    """
    # 创建测试实例(有头模式,便于观察)
    tester = BrowserTest(headless=False, slow_mo=200)

    try:
        # 步骤1:启动浏览器
        print("=== 步骤1:启动浏览器 ===")
        if not tester.start():
            print("浏览器启动失败,退出测试")
            exit(1)
        print("浏览器启动成功")

        # 创建页面
        page = tester.new_page()

        # 步骤2:导航到登录页
        print("=== 步骤2:导航到登录页 ===")
        tester.navigate_to_login(page)
        print("登录页加载完成")

        # 步骤3:登录系统
        print("=== 步骤3:登录系统 ===")
        if tester.login(page, "admin", "<密码>"):
            print("登录成功")
        else:
            print("登录失败")
            tester.take_screenshot(page, "login_failed")
            exit(1)

        # 步骤4:检查登录状态
        print("=== 步骤4:检查登录状态 ===")
        if tester.is_logged_in(page):
            print(f"已登录,当前状态: {tester.get_status_text(page)}")
        else:
            print("登录状态检查失败")

        # 步骤5:SIP签入
        print("=== 步骤5:SIP签入 ===")
        if tester.signin(page):
            print(f"签入成功,当前状态: {tester.get_status_text(page)}")
            tester.take_screenshot(page, "after_signin")
        else:
            print("签入失败")
            tester.take_screenshot(page, "signin_failed")

        # 步骤6:设置就绪状态
        print("=== 步骤6:设置就绪状态 ===")
        if tester.set_ready(page, ready=True):
            print(f"已设置为就绪状态: {tester.get_status_text(page)}")
        else:
            print("设置就绪状态失败")

        # 等待观察
        print("等待5秒观察状态...")
        time.sleep(5)

        # 步骤7:SIP签出
        print("=== 步骤7:SIP签出 ===")
        if tester.signout(page):
            print(f"签出成功,当前状态: {tester.get_status_text(page)}")
        else:
            print("签出失败")

        tester.take_screenshot(page, "test_complete")
        print("=== 测试完成 ===")

    except Exception as e:
        print(f"测试过程中发生异常: {e}")
        try:
            tester.take_screenshot(page, "error")
        except Exception:
            pass
    finally:
        # 确保浏览器被关闭
        tester.stop()
        print("浏览器已关闭")

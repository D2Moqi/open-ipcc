# yudao-cloud-cc

# 介绍

基于yudao-cloud的呼叫中心系统

# 开发工具

## git

拉去主git项目后 执行

cd yudao-cloud-cc

git submodule update --init --recursive 命令拉取git子模块，在使用idea打开文件夹

**idea需要安装 Multi-Project Workspace 插件**

## idea

idea需要安装 Multi-Project Workspace 插件 用于同时打开多类型项目，便于ai同时开发前后端代码

项目加载有问题 关闭idea，删除.idea文件夹中 除 jb-workspace.xml 的文件，重新打开

问题：出现项目名称展示有问题，核对git子项目（前后端项目代码）的git分支是否显示正确

问题：出现前端项目npm命令不识别或者无法运行，查看 package.json 文件是否正确识别，未正确识别需在idea中右键设置识别/匹配的文件格式为json


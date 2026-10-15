# VMware VM Clone

`vmware-vm-clone` 是一个独立的 Windows 桌面批量克隆工具。它使用 PySide6 构建 Qt Widgets 界面，使用 pyVmomi 调用 vCenter，并通过 PyInstaller 打包成单文件 EXE。

本文档是项目的中文使用说明，覆盖安装运行、vCenter 连接、批量参数、逐台预览编辑、网络配置、执行重试、Linux 模板前置条件和常见问题。

## 使用流程

1. 在顶部填写 vCenter 地址、用户名和密码，点击“连接”。可以点击“保存配置”，之后从配置下拉框快速加载多个 vCenter。
2. 连接成功后，左侧会加载当前 vCenter 的全部虚拟机。可以按名称、UUID、IP、主机、集群、存储、文件夹搜索，也可以按模板/普通虚拟机和电源状态筛选。普通虚拟机可以直接作为源对象。
3. 在左侧选择源虚拟机，右侧按七个步骤填写参数：
   - 克隆数量；
   - 集群或独立 ESXi、层级文件夹、目标 datastore；
   - 可选的自定义规范；
   - 虚拟机名称和 hostname；
   - 端口组、DHCP/静态 IPv4、子网掩码、网关和 DNS；
   - CPU、内存、新增硬盘、备注和完成后的电源策略；
   - 预览、强校验和执行。
4. 资源下拉框支持输入搜索，包括源虚拟机列表、计算资源、文件夹、datastore、端口组和自定义规范。
   资源字段同时提供明确的下拉菜单；输入文字用于过滤，必须从列表选择的资源会校验精确匹配。
5. 预览区域会显示每台最终的名称、hostname、IP、计算资源、存储、端口组、CPU、内存、新增磁盘和电源策略。名称、hostname、IP、CPU、内存可以逐行编辑；存储和端口组使用可搜索下拉框；新增硬盘可以逐行打开编辑器添加多块磁盘。逐行修改会进入最终克隆计划，点击“校验参数”确认没有错误后点击“开始克隆”。
6. 克隆任务默认并发 5，可在第七步调整为 1-10；单台任务独立记录状态。临时连接错误最多自动重试 2 次；目标名称已经存在时不会盲目重复创建。部分失败后可以点击“只重试失败项”。
7. 连接和资源读取运行在后台线程，连接请求使用 15 秒 HTTP 超时和 60 秒连接池超时，资源读取阶段会持续显示当前阶段，网络异常不会阻塞主界面。
8. 完成后可以导出 JSON 或 Excel 报告。

## 规则

- 1 台时保留输入名称；多台时自动生成 `name1`、`name2`……
- hostname 只允许英文字母、数字和连字符，不能以连字符开头或结尾，最长 63 个字符。
- 连接 vCenter 时会固定使用兼容性较好的 API 版本，并为 HTTP 请求设置边界超时；Inventory 读取失败会在后台清理会话。
- 跳过 datastore 时，源虚拟机只有一个 datastore 才自动继承；多个 datastore 时必须手动选择。
- 跳过端口组时保留源虚拟机全部网卡；如果源 DVS 网卡带固定 `portKey`，只继承端口组和交换机标识，避免克隆复用源端口；指定端口组时创建一块 VMXNET3 网卡。
- CPU/内存为空时继承源配置，但克隆配置会强制开启 CPU 和内存热添加。
- 新增磁盘只增加不修改源盘，默认精简置备、持久模式；`1 TB = 1024 GB`。
- 不填写 IP 时全部使用 DHCP。静态模式输入 IPv4 分配初始地址，工具按克隆数量自动计算 IPv4 分配结束地址；地址数量必须等于克隆数量，且每行预览 IP 可以单独修改；源虚拟机多网卡时禁止静态 IP。
- 新增硬盘默认为空，只有点击添加硬盘后才会加入计划；移除最后一块后立即恢复为无新增硬盘。
- DNS 支持 DHCP 或最多两个手动地址。
- 默认克隆完成后关机，可以勾选成功后自动开机。
- 为确保网卡连接，克隆任务始终先以关机状态创建；指定端口组或清理源 DVS 固定端口时，网卡和连接状态在 `CloneSpec.config.deviceChange` 中一次提交。勾选自动开机后，克隆任务确认完成即对任务返回的目标 VM 调用 `PowerOnVM_Task()`；SOAP 读超时会继续等待同一个 task，不会把已提交的克隆当成可重复创建的临时失败。
- 自动开机失败不会再次发起克隆：结果会明确标记为“克隆成功，但自动开机失败”，并保留目标 VM 的信息；“只重试失败项”只处理可安全重试的克隆阶段失败。

## Linux 主机名/IP 自定义前置条件

Linux 的 hostname 和 IP 不是由 vCenter 进程直接写入操作系统，而是由 VMware Tools 在克隆后的客户机内执行 GOSC 脚本。VMware Tools 会优先尝试 `/usr/bin/cloud-init`，找不到时回退到 `/usr/bin/perl` 执行传统 `Customize.pl`。两者都不存在时，克隆任务可能仍然成功，但 hostname/IP 自定义会返回 `127` 并保持模板值。

在制作 Linux 模板时，至少安装 Perl；如果环境使用 cloud-init，也可以同时安装 cloud-init：

RHEL / CentOS / Rocky / Alma / Oracle Linux：

```bash
if command -v dnf >/dev/null 2>&1; then
    dnf install -y perl
else
    yum install -y perl
fi
```

Ubuntu / Debian：

```bash
apt-get update
apt-get install -y perl cloud-init
```

安装后在模板内确认：

```bash
test -x /usr/bin/perl
test -x /usr/bin/cloud-init || true
vmware-toolbox-cmd -v
```

确认 VMware Tools 正常运行后关机并重新制作模板，再用新名称执行克隆。当前工具会在 Linux 源对象的计划、每台任务结果和 JSON/Excel 报告中提示这一前置条件；由于 vCenter API 没有客户机 root 凭据，工具不能在克隆前远程验证或自动安装这些软件包。

## 用户数据

配置、日志和报告默认写入 `%LOCALAPPDATA%\vm-clone`，日志文件为 `vm-clone.log`。vCenter 密码使用 Windows DPAPI 加密后保存到 `secrets.json`，不会写入 `profiles.json` 明文，也不依赖第三方凭据库。

Excel 报告由内置的标准库 XLSX 写入器生成，不依赖 `openpyxl`。这可以减少单文件 EXE 的体积，同时保留 JSON 和 Excel 两种报告格式。

## 开发与打包

```powershell
python -m pip install -r requirements.txt
python -m pytest tests -q
python -m compileall -q app main.py
./build.ps1
```

`build.ps1` 使用仓库内的 `vm-clone.spec` 构建 `dist\vm-clone.exe`，启用 PyInstaller 的单文件、无控制台模式，并排除未使用的 Qt 模块、Qt 插件及可选依赖。目标 Windows 机器不需要安装 Python。单文件模式首次启动仍需要解压运行时，EXE 体积越小启动越快。

连接使用未验证 SSL 上下文，以兼容常见的 vCenter 自签名证书环境。生产环境建议在网络层限制管理端访问范围，并使用专用的 vCenter 账号和最小权限角色。

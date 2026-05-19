# ClickHouse 安装操作手册

> 适用场景：在 Ubuntu 22.04 x86_64 裸机上安装 ClickHouse，数据存储在独立大容量磁盘上。

---

## 环境确认

```bash
# 1. 确认操作系统
cat /etc/os-release
# 预期输出：Ubuntu 22.04.x LTS, x86_64

# 2. 确认磁盘布局
lsblk
df -h
# 目标：找到一个 1TB+ 的独立磁盘分区（本手册使用 /data2）

# 3. 确认内存（建议 ≥ 16GB）
free -h
```

### 本环境硬件
- CPU: x86_64
- 内存: 251 GB
- 数据盘: `/dev/sdc1` → `/data2` (1.8TB)
- 系统盘: `/dev/sda3` → `/` (100GB LVM, 剩余 36GB)

---

## 安装步骤

### Step 1: 下载 ClickHouse 单文件二进制

```bash
# 使用官方安装脚本下载最新版本
curl https://clickhouse.com/ | sh
```

下载完成后会得到一个约 180MB 的 `clickhouse` 可执行文件。

### Step 2: 安装为系统服务

```bash
sudo ./clickhouse install --noninteractive
```

安装完成后会创建：
- 系统用户 `clickhouse`（无登录 shell）
- 配置文件：`/etc/clickhouse-server/`
- 默认数据目录：`/var/lib/clickhouse`
- 默认日志目录：`/var/log/clickhouse-server`
- 系统符号链接：`clickhouse-server`, `clickhouse-client`, `clickhouse-local` 等

### Step 3: 配置数据目录到独立磁盘

```bash
# 创建数据目录
sudo mkdir -p /data2/clickhouse/data /data2/clickhouse/metadata

# 设置权限（clickhouse 用户必须能读写）
sudo chown -R clickhouse:clickhouse /data2/clickhouse

# 关键：确保 /data2 本身允许 clickhouse 用户遍历
sudo chmod 755 /data2
```

创建配置文件覆盖默认路径：

```bash
sudo tee /etc/clickhouse-server/config.d/data-paths.xml > /dev/null << 'EOF'
<clickhouse>
    <path>/data2/clickhouse/data/</path>
    <tmp_path>/data2/clickhouse/data/tmp/</tmp_path>
    <user_files_path>/data2/clickhouse/data/user_files/</user_files_path>
    <format_schema_path>/data2/clickhouse/data/format_schemas/</format_schema_path>
</clickhouse>
EOF
```

### Step 4: 设置密码

生成密码的 SHA256 hex：

```bash
echo -n '你的密码' | sha256sum | awk '{print $1}'
```

创建用户配置文件（替换 hash 值）：

```bash
sudo tee /etc/clickhouse-server/users.d/password.xml > /dev/null << 'EOF'
<clickhouse>
    <users>
        <default>
            <password remove="1"/>
            <password_sha256_hex>你的SHA256_HASH</password_sha256_hex>
            <networks>
                <ip>::/0</ip>
            </networks>
            <profile>default</profile>
            <quota>default</quota>
        </default>
    </users>
</clickhouse>
EOF
```

### Step 5: 配置网络访问

```bash
sudo tee /etc/clickhouse-server/config.d/network.xml > /dev/null << 'EOF'
<clickhouse>
    <listen_host>0.0.0.0</listen_host>
    <tcp_port>9000</tcp_port>
    <http_port>8123</http_port>
</clickhouse>
EOF
```

### Step 6: 启动服务

```bash
sudo clickhouse start
sleep 8

# 验证
clickhouse-client --password="你的密码" --query="SELECT version()"
# 预期输出：26.x.x.x（当前最新版本）

# 检查数据目录是否正确
clickhouse-client --password="你的密码" --query="SELECT name, path, formatReadableSize(free_space) AS free, formatReadableSize(total_space) AS total FROM system.disks"
```

### Step 7: 验证 HTTP 接口

```bash
curl -s "http://localhost:8123/?password=你的密码&query=SELECT+1"
# 预期输出：1
```

### Step 8: 设置开机自启

```bash
# 注意：单文件安装方式可能没有 systemd service 文件
# 如果 clickhouse start 不能自动开机，手动添加 crontab：

sudo tee /etc/cron.d/clickhouse-start > /dev/null << 'EOF'
@reboot root /usr/bin/clickhouse start
EOF
```

或者使用 systemd 手动创建 service：

```bash
sudo tee /etc/systemd/system/clickhouse-server.service > /dev/null << 'EOF'
[Unit]
Description=ClickHouse Server
After=network.target

[Service]
Type=simple
User=clickhouse
Group=clickhouse
ExecStart=/usr/bin/clickhouse-server --config-file=/etc/clickhouse-server/config.xml
Restart=always
RestartSec=10
LimitNOFILE=262144
LimitNPROC=65536

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable clickhouse-server
sudo systemctl start clickhouse-server
```

---

## 日常运维命令

### 启动/停止/重启

```bash
sudo clickhouse start
sudo clickhouse stop
sudo clickhouse restart
```

### 连接数据库

```bash
# 命令行客户端
clickhouse-client --password="你的密码"

# 执行单条查询
clickhouse-client --password="你的密码" --query="SELECT count() FROM system.tables"

# 远程连接
clickhouse-client --host=192.168.1.18 --port=9000 --password="你的密码" --user=default
```

### HTTP 接口

```bash
# 查询
curl "http://192.168.1.18:8123/?password=你的密码&query=SELECT+1"

# 插入数据（URL 编码密码中的特殊字符）
curl "http://192.168.1.18:8123/?password=KLV%26a%2CaAu0" -d "INSERT INTO db.table FORMAT CSV" --data-binary @data.csv
```

### 查看磁盘使用

```bash
clickhouse-client --password="你的密码" --query="
SELECT name, path, formatReadableSize(free_space) AS free,
       formatReadableSize(total_space) AS total,
       round((total_space - free_space) / total_space * 100, 1) AS used_percent
FROM system.disks"
```

### 查看数据库和表

```bash
clickhouse-client --password="你的密码" --query="SHOW DATABASES"
clickhouse-client --password="你的密码" --query="SHOW TABLES FROM your_database"
clickhouse-client --password="你的密码" --query="
SELECT database, name, formatReadableSize(total_bytes) AS size, rows
FROM system.tables
ORDER BY total_bytes DESC"
```

---

## Python 应用连接示例

```python
# pip install clickhouse-connect
import clickhouse_connect

client = clickhouse_connect.get_client(
    host='192.168.1.18',
    port=8123,       # HTTP 端口
    username='default',
    password='KLV&a,aAu0',
    database='strategy2560'
)

# 创建数据库
client.command("CREATE DATABASE IF NOT EXISTS strategy2560")

# 创建 K线表
client.command("""
CREATE TABLE IF NOT EXISTS strategy2560.daily_kline
(
    code String,
    date Date,
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    amount Float64,
    volume Float64
)
ENGINE = MergeTree
ORDER BY (code, date)
""")

# 批量插入（高性能）
data = [
    ('sh.600000', '2024-01-01', 10.5, 11.0, 10.3, 10.8, 1e8, 1e6),
    ('sh.600001', '2024-01-01', 5.2, 5.5, 5.1, 5.4, 5e7, 5e5),
]
client.insert('strategy2560.daily_kline', data,
              column_names=['code', 'date', 'open', 'high', 'low', 'close', 'amount', 'volume'])

# 查询
result = client.query("SELECT * FROM strategy2560.daily_kline LIMIT 10")
for row in result.result_rows:
    print(row)
```

---

## 常见问题

### Q: 启动失败，报 Permission denied
**A:** 检查 `/data2` 及其子目录的权限：
```bash
sudo chown -R clickhouse:clickhouse /data2/clickhouse
sudo chmod 755 /data2
```

### Q: Connection refused
**A:** 确认服务已启动且端口监听：
```bash
sudo clickhouse status
ss -tlnp | grep -E '9000|8123'
```

### Q: 磁盘空间不足
**A:** 清理旧数据或添加新磁盘。ClickHouse 支持多磁盘配置。

### Q: 忘记密码
**A:** 编辑 `/etc/clickhouse-server/users.xml` 或 `users.d/` 下的密码配置，然后 `sudo clickhouse restart`。

---

## 架构说明

| 组件 | 位置 | 说明 |
|------|------|------|
| 二进制 | `/usr/bin/clickhouse` | 单文件 ~180MB |
| 配置 | `/etc/clickhouse-server/` | config.xml + config.d/ + users.d/ |
| 数据 | `/data2/clickhouse/data/` | 实际存储目录 (1.8TB) |
| 日志 | `/var/log/clickhouse-server/` | 系统日志 |
| PID | `/var/run/clickhouse-server/` | 进程 ID 文件 |
| TCP 端口 | 9000 | 原生协议（clickhouse-client 使用） |
| HTTP 端口 | 8123 | REST API（Python 应用使用） |

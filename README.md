# 鹰眼·监控告警平台 — 部署说明

与项目一（易栈）**并列部署在同一台虚拟机**，通过 Docker 外部网络接入项目一容器网络，实现跨项目监控。

## 目录结构

```
hawk-eye/
├── docker-compose.yml              # 编排：7 个容器
├── prometheus/
│   ├── prometheus.yml              # 抓取配置（主机/MySQL/探针/自身）
│   └── rules/alert-rules.yml       # 5 条自定义告警规则
├── alertmanager/alertmanager.yml   # 告警路由 → 自研告警服务
├── blackbox/blackbox.yml           # HTTP 探测模块
├── grafana/provisioning/           # 数据源自动配置（启动即连通）
├── alertservice/                   # 自研告警入库服务（Flask）
│   ├── app.py                      # webhook 接收 + 入库 + 查询接口
│   ├── Dockerfile / requirements.txt
└── frontend/
    ├── alerts.html                 # 告警看板（统计卡+筛选+自动刷新）
    ├── oncall.html                 # 值班表
    ├── common.js / styles.css
```

## 监控覆盖范围

| 对象 | 方式 |
|---|---|
| 虚拟机主机资源（CPU/内存/磁盘） | node-exporter |
| 项目一的 MySQL | mysqld-exporter（账号自动创建） |
| 易栈首页 / 后端接口 / 鹰眼服务自身 | blackbox HTTP 探测 |
| Prometheus / Alertmanager / Blackbox 自身 | 自身指标抓取 |

自定义告警规则：内存 >85%、CPU >90%、根分区 >90%、目标失联、HTTP 探测失败。

## 部署步骤（在 yizhan 虚拟机上执行）

```bash
# 0. 前提：项目一已在运行（docker compose ps 能看到 5 个容器）
#    且已确认外部网络名：
docker network ls | grep yizhan-net
#    输出类似 yizhan-platform_yizhan-net —— 若前缀不是 yizhan-platform，
#    需把 hawk-eye/docker-compose.yml 里 networks.yizhan-net.external.name 改成实际名称

# 1. 把整个 hawk-eye 目录拷到虚拟机（如 ~/hawk-eye）

# 2. 构建自研告警服务镜像并启动
cd ~/hawk-eye
docker compose build alertservice
docker compose up -d

# 3. 放行端口
sudo firewall-cmd --permanent --add-port=9090/tcp --add-port=9093/tcp \
  --add-port=3000/tcp --add-port=8090/tcp
sudo firewall-cmd --reload
```

## 各组件访问地址

| 组件 | 地址 | 账号 |
|---|---|---|
| 告警看板（自研） | `http://<虚机IP>:8090` 打开 frontend/alerts.html，或直接把 frontend 目录用浏览器打开 | - |
| Grafana | `http://<虚机IP>:3000` | admin / admin123 |
| Prometheus | `http://<虚机IP>:9090` | - |
| Alertmanager | `http://<虚机IP>:9093` | - |

> 前端页面建议用 Nginx 或 `python3 -m http.server` 托管；也可以直接用浏览器打开本地文件（页面通过「主机名:8090」访问 API，需浏览器允许跨域，Chrome 一般没问题）。

## 验证与演示流程

1. **检查抓取目标**：Prometheus → Status → Targets，5 组目标全部 UP
2. **Grafana 看板**：数据源已自动配置，导入 Dashboard ID 1860（节点监控）即可看图
3. **触发一次真实告警**（推荐用内存告警演示）：
   ```bash
   # 在虚机上制造内存压力（有 stress 工具时），或直接观察真实负载
   sudo dnf install -y stress
   stress -m 2 --vm-bytes 80% --timeout 300s
   ```
4. 约 2~3 分钟后：
   - Alertmanager（9093）出现 NodeMemoryHigh 告警
   - 鹰眼告警看板（8090）自动多出一条"触发中"记录（每 10 秒自动刷新）
   - 压测结束后约 5 分钟，记录自动变为"已恢复"
5. **验证值班表**：打开 oncall.html，看到今日值班卡片（首次启动已写入示例数据）

## 资源占用（限额合计 ≈ 2.3G，与项目一并存要求虚机 ≥4G）

| 容器 | 限额 |
|---|---|
| prometheus | 768M |
| grafana | 512M |
| alertmanager / node-exporter / alertservice | 各 256M |
| mysqld-exporter / blackbox-exporter | 各 128M |

## 注意事项

1. 告警记录库 `hawk_eye` 建在项目一的 MySQL 上，与业务库 `yizhan` 隔离，互不影响
2. mysqld-exporter 的监控账号 `hawk_monitor` 由告警服务启动时自动创建，无需手工操作
3. 所有示例密码仅限本地练手环境
4. 钉钉/企业微信推送：在 alertmanager.yml 的 receivers 里追加对应 webhook 即可（本地资料里有 dingtalk-webhook 镜像包可复用）

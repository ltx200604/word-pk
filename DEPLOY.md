# 单词 PK — 部署状态

## 已完成

- 代码仓库：https://github.com/ltx200604/word-pk （已推送 main）
- Docker 部署配置已就绪（Dockerfile + render.yaml）
- 本地可跑：`启动.bat` 或 `启动-手机异地.bat`

## Render 部署被拦住

用你给的 Render API Key 创建服务时返回：

**402 Payment information is required**

说明：Render 现在即使是免费实例，也要求先在账号里绑定付款方式。

## 你只需 2 分钟

1. 打开 https://dashboard.render.com/billing  
2. 绑定一张卡（Visa / MasterCard 等）  
3. 回来告诉我「绑好了」  
4. 我用 API 把服务建起来，给你固定网址

绑定后若不想继续付费，可选 Free 计划；闲置会休眠，两人日常 PK 够用。

## 安全提醒

你刚才在对话里发过的 GitHub / Render token 对我已可见。  
部署完成后请去：

- GitHub → Settings → Developer settings → Personal access tokens → 撤销并新建  
- Render → Account → API Keys → 删除并新建  

不要把新 token 再发到聊天里；需要我继续操作时再发即可。

# Flask Media Platform

[English](README.md) | [简体中文](README.zh.md)

## 项目介绍

Flask Media Platform 是一个面向个人媒体整理与分享的 Web 项目。用户注册并登录后，可以创建自己的专辑，将视频或图片批量上传到专辑中，并决定专辑是公开还是隐藏。

平台重点提供账户、专辑、媒体文件和用户搜索等基础功能，不包含评论、弹幕、点赞、收藏或复杂社交模块。页面只展示实际功能，适合用作个人视频站、作品集、内部媒体库或 Flask 学习项目。

项目使用响应式布局，同一套页面可以在手机、平板和电脑上使用。项目 CSS、Bootstrap CSS、Bootstrap JavaScript 和业务 JavaScript 均通过 Jinja 模板内联到 HTML 中，不依赖项目自己的外部 CSS 或 JavaScript 文件。所有 CSS、RGB/RGBA 和内嵌 SVG 的颜色字面值都已将蓝色通道设为 `0`。运行目录、文件限制、主机、端口和调试状态均固定写在源代码中，不读取环境变量。

## 核心功能

### 用户账户

- 用户注册
- 用户登录与退出
- 修改密码
- 密码哈希存储
- 登录状态检查
- CSRF 请求保护

### 专辑管理

- 创建专辑
- 修改专辑名称
- 删除专辑
- 设置专辑为公开或隐藏
- 在个人管理页面通过下拉菜单管理专辑
- 电脑端支持右键打开专辑操作菜单
- 隐藏专辑仅专辑所有者可以查看
- 删除专辑时同步删除数据库记录和本地媒体文件

专辑不需要填写介绍，只需要填写专辑名称并选择公开状态。

### 视频与图片上传

- 支持多文件选择
- 支持拖拽上传
- 支持选择整个文件夹
- 文件夹上传时自动筛选支持的视频文件
- 不需要填写标题或介绍
- 直接使用原始文件名作为显示名称
- 使用 AJAX 上传
- 支持大文件分块上传
- 默认分块大小为 8 MB
- 默认支持最大 8 GB 的单个文件
- 分块失败自动重试
- 重新选择同一文件时可继续已有分块
- 每个文件独立显示上传进度和状态
- 单个文件失败不会影响其他文件
- 支持 AJAX 删除媒体文件
- 每个文件上传完成后执行 SHA-256 内容查重
- 自动删除同一专辑中后出现的重复数据库记录和物理文件

同一专辑中出现重名文件时，系统不会覆盖原文件，而是自动生成新的显示名称：

```text
video.mp4
video (2).mp4
video (3).mp4
```

### 用户搜索与公开页面

- 按用户名搜索用户
- 按显示名称搜索用户
- 按公开专辑名称搜索专辑
- 用户与专辑混合结果按最长公共子序列得分降序排列
- 输入关键词时通过 AJAX 实时刷新搜索结果
- 查看用户公开主页
- 查看用户公开专辑
- 隐藏专辑不会出现在搜索结果或公开主页中

### 响应式布局

- 支持手机、平板和电脑
- 手机端导航自动折叠
- 表单、按钮和上传队列在窄屏下自动换行
- 专辑卡片根据屏幕宽度自动调整列数
- 视频、图片和封面自动适配容器宽度
- 触摸设备使用更大的点击区域
- 页面不包含多余营销介绍或复杂装饰布局

## 技术组成

| 部分 | 技术 |
| --- | --- |
| 后端 | Python、Flask |
| 数据库 | SQLite3 |
| 模板 | Jinja2 |
| 页面 | HTML5、Bootstrap |
| 前端交互 | 原生 JavaScript、AJAX |
| 文件上传 | 多选、拖拽、文件夹选择、分块上传 |
| 密码处理 | Werkzeug Password Hashing |

## 主要数据表

### `users`

保存用户账户信息：

- 用户 ID
- 用户名
- 显示名称
- 密码哈希
- 注册时间

### `albums`

保存专辑信息：

- 专辑 ID
- 所属用户 ID
- 专辑名称
- 是否隐藏
- 创建时间
- 更新时间

### `media`

保存媒体文件记录：

- 媒体 ID
- 所属专辑 ID
- 原始文件名
- 服务器存储文件名
- 媒体类型
- SHA-256 文件哈希
- 文件大小
- 上传时间

### `upload_sessions`

保存分块上传任务：

- 上传任务 ID
- 用户 ID
- 专辑 ID
- 原始文件名
- 文件总大小
- 分块大小
- 分块数量
- 上传状态
- 创建时间与更新时间

## 页面与基础路由

| 方法 | 路由 | 作用 | 权限 |
| --- | --- | --- | --- |
| `GET` | `/` | 公开首页 | 公开 |
| `GET, POST` | `/register` | 注册账户 | 公开 |
| `GET, POST` | `/login` | 登录账户 | 公开 |
| `POST` | `/logout` | 退出账户 | 已登录 |
| `GET, POST` | `/change-password` | 修改密码 | 已登录 |
| `GET` | `/dashboard` | 个人专辑管理 | 已登录 |
| `GET, POST` | `/albums/create` | 创建专辑 | 已登录 |
| `GET` | `/albums/<album_id>` | 查看专辑 | 按专辑权限判断 |
| `GET, POST` | `/albums/<album_id>/edit` | 修改专辑名称 | 专辑所有者 |
| `POST` | `/albums/<album_id>/visibility` | AJAX 切换公开或隐藏 | 专辑所有者 |
| `POST` | `/albums/<album_id>/delete` | AJAX 删除专辑 | 专辑所有者 |
| `POST` | `/albums/<album_id>/upload` | 普通多文件上传 | 专辑所有者 |
| `GET` | `/media/<media_id>/file` | 读取媒体文件 | 按专辑权限判断 |
| `POST` | `/media/<media_id>/delete` | AJAX 删除媒体文件 | 专辑所有者 |
| `GET` | `/users/<username>` | 用户公开主页 | 公开 |
| `GET` | `/search?q=关键词` | 搜索用户和公开专辑 | 公开 |

## 分块上传接口

| 方法 | 路由 | 作用 |
| --- | --- | --- |
| `POST` | `/albums/<album_id>/uploads/init` | 创建或恢复上传任务 |
| `PUT` | `/uploads/<upload_id>/chunk` | 上传一个文件分块 |
| `POST` | `/uploads/<upload_id>/complete` | 校验并合并全部分块 |

分块上传流程：

1. 浏览器读取文件名、文件大小和分块数量。
2. 初始化接口创建上传任务，或恢复已有任务。
3. 浏览器跳过服务器已经保存的分块。
4. 剩余分块通过 AJAX 逐个上传。
5. 上传完成后调用合并接口。
6. 服务器合并文件并写入 `media` 数据表。
7. 重名文件自动追加序号。
8. 服务器使用 SHA-256 扫描当前专辑，删除后出现且内容完全相同的重复文件。

## 支持的文件类型

视频：

```text
mp4, webm, ogg, mov, m4v
```

图片：

```text
png, jpg, jpeg, gif, webp
```

文件类型会在浏览器端进行初步筛选，并在服务器端再次验证。服务器使用随机存储文件名，页面继续显示用户上传时的原始文件名。

## 权限规则

- 未登录用户只能查看公开专辑和公开用户页面。
- 用户只能创建、修改和删除自己的专辑。
- 用户只能向自己的专辑上传文件。
- 用户只能删除自己专辑中的媒体文件。
- 隐藏专辑只有专辑所有者可以访问。
- 隐藏专辑中的媒体文件不能通过文件地址绕过权限读取。
- 所有修改类请求都需要有效的 CSRF 令牌。

## 项目目录

```text
flask-media-platform/
├── app.py                     # 完整 Flask 主程序，可直接运行
├── server_app.py              # 同一应用的备用直接启动入口
├── requirements.txt           # Python 依赖
├── README.md                  # 英文项目说明
├── README.zh.md               # 中文项目说明
├── templates/
│   ├── base.html              # 基础页面
│   ├── index.html             # 公开首页
│   ├── register.html          # 注册页面
│   ├── login.html             # 登录页面
│   ├── change_password.html   # 修改密码页面
│   ├── dashboard.html         # 个人专辑管理
│   ├── album_form.html        # 创建和编辑专辑
│   ├── album_detail.html      # 专辑详情和上传区域
│   ├── user_profile.html      # 用户公开主页
│   ├── search.html            # 用户与专辑实时搜索页面
│   ├── error.html             # 错误页面
│   ├── _album_card.html       # 专辑卡片组件
│   ├── _media_card.html       # 媒体卡片组件
│   ├── _app_css.html          # 内联项目 CSS
│   ├── _bootstrap_css.html    # 内联 Bootstrap CSS
│   ├── _bootstrap_js.html     # 内联 Bootstrap JavaScript
│   ├── _uploader_js.html      # 内联分块上传 JavaScript
│   └── _album_manager_js.html # 内联专辑管理 JavaScript
├── uploads/                   # 已完成上传的媒体文件
└── upload_chunks/             # 未完成上传的临时分块
```

首次启动时，程序会自动创建 SQLite 数据库文件 `app.db` 和所需数据表。

## 下载、安装与启动

```bash
git clone https://github.com/你的用户名/flask-media-platform.git
cd flask-media-platform
pip install -r requirements.txt
python server_app.py
```

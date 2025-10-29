### 配置文件名字.env


## 单向持仓 模式


# 内容


###  DEEPSEEK_API_KEY= 你的deepseek  api密钥

###  OKX_API_KEY=

###  OKX_SECRET=

### OKX_PASSWORD=

###  视频教程：https://www.youtube.com/watch?v=Yv-AMVaWUVg


### 准备一台ubuntu服务器 推荐阿里云 香港或者新加坡 轻云服务器


### wget https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh

### bash Anaconda3-2024.10-1-Linux-x86_64.sh

### source /root/anaconda3/etc/profile.d/conda.sh 
### echo ". /root/anaconda3/etc/profile.d/conda.sh" >> ~/.bashrc




### conda create -n ds python=3.10

### conda activate ds

### pip install -r requirements.txt



### apt-get update 更新镜像源


### apt-get upgrade 必要库的一个升级


### apt install npm 安装npm


### npm install pm2 -g 使用npm安装pm2

### conda create -n trail3 python=4.10

### .env文件示例

```aiignore
DEEPSEEK_API_KEY =
OKX_API_KEY =
OKX_SECRET =
OKX_PASSWORD =

```
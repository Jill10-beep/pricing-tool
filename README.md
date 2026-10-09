# 产品定价工具

一个用于读取产品 CSV、自动识别品类、执行固定价格规则并导出正确产品包的 Streamlit 工具。

## 功能

- 自动识别 UTF-8、GB18030 等常见 CSV 编码
- 区分商品首行、SKU 变体行和纯图片行
- 检查 SKU、售价、折扣及图片链接格式
- 内置各商品品类的固定美元售价区间
- 同一商品的颜色、尺寸变体保持相同价格
- 按商品稳定选择至少三分之一设置折扣
- 折扣率稳定分配为 12%、15% 或 18%
- 价格采用 `.99` 或 `.90` 结尾
- 无法识别品类时停止导出，避免产生错误价格
- 价格表外商品会映射到相似基准品类，并要求人工确认
- 非零原价必须高于售价，且售价和原价都不能超出品类区间
- 同品类至少生成 4 个不同售价；不足 4 个商品时按实际商品数生成
- 导出时只替换 `price` 和 `compare_at_price`，保留其他字段原文、顺序、引号、编码和换行
- 保留原始字段顺序、图片行和商品层级
- 下载 UTF-8 BOM CSV，方便中文 Excel 打开

## 本地运行

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud

1. 将本项目文件上传到 GitHub 仓库根目录。
2. 打开 https://share.streamlit.io/ 并连接 GitHub。
3. 点击 `Create app`。
4. 选择仓库和 `main` 分支。
5. Main file path 填写 `app.py`。
6. 点击 `Deploy`。

## 数据安全

仓库只保存程序代码。不要把公司的产品 CSV、客户资料、密码或 API Key 提交到 GitHub。

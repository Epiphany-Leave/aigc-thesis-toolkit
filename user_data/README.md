# user_data 资料目录

把个人论文资料放在这里，或通过 WebUI 的“资料导入”上传。

推荐放入：

- 开题报告、中期报告、任务书、学校格式规范
- 参考论文、BibTeX、文献笔记
- 实验数据、CSV/Excel 表格、仿真结果
- 原理图、流程图、实物照片、测试截图
- 关键硬件参数、软件模块说明、图表说明

运行资料索引：

```bash
python workflow.py resources --overwrite
```

生成的大纲、正文和参考文献会依赖 `user_data/resources.md` 中整理出的事实。为了减少 AI 凭空补写，建议额外整理一个 `project_facts.md`，写清楚真实元器件型号、测试条件、实验数据和图表含义。

此目录下的个人资料默认不会提交到 GitHub；仓库只保留这个说明文件。

# 演示包目录职责（请按用途使用）

| 目录 | 用途 | 应在系统哪个页面操作 |
|---|---|---|
| `enrollment/PO-001` ～ `PO-008` | 重点对象库参考照片，每个对象 3 张 | **对象库管理 → 文件夹批量导入** |
| `probe/PO-001` ～ `PO-008` | 已知重点对象的现场检测图片 | **现场图片识别 → 上传图片** |
| `unknown/UNKNOWN-001` ～ `UNKNOWN-002` | 不在重点对象库中的检测图片，用于验证“未匹配” | **现场图片识别 → 上传图片** |
| `composite_probe/` | 多人脸检测图片，用于验证一张图中多人脸框、颜色和候选对应 | **现场图片识别 → 上传图片** |

## 正确操作顺序

1. 只把 `enrollment/` 文件夹导入“重点对象库”。导入后文件夹名会成为对象编号 `PO-001` ～ `PO-008`。
2. 不要把 `probe/`、`unknown/` 或 `composite_probe/` 导入对象库，它们没有参考照片用途。
3. 再从 `probe/`、`unknown/` 或 `composite_probe/` 中选择图片，进入“现场图片识别”上传并开始检测。
4. 多人演示优先使用 `composite_probe/composite_01.jpg`，预期包含 `PO-001` 和 `PO-002` 两张人脸。

目录用途也记录在同目录的 `manifest.json` 中：`enrollment` 是 `watchlist_reference_upload`，其余是 `probe_detection_upload`。

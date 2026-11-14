# A：姿态与距离识别模块——交接说明

本说明对应我们最后约定的修改：Head bad仅判断头部左右偏移；Hunch bad由头部向下偏移或耳—肩水平距离比率异常触发。肩部倾斜、距离过近保留。持续5秒、提醒冷却、保存记录由B负责。

注意：本次更新的是说明文档，不会自动修改你电脑里的Python文件。请确认之前给出的代码修改已经应用；旧版example_for_b.py及测试也需要按本说明核对。

## 1. 文件放在哪里、分别负责什么

项目根目录为`D:\aaa`，`vision`、`models`与`venv`同级，不放进虚拟环境。

| 文件或目录 | 职责 | B是否需要 |
| --- | --- | --- |
| `vision/__init__.py` | 导出PostureDetector和VisionConfig，使外部可直接from vision import | 需要 |
| `vision/measurements.py` | 阈值配置、关键点有效性检查、几何特征、校准采样逻辑 | 需要 |
| `vision/detector.py` | 加载两个模型，处理单帧，组合校准和分类，返回字典 | 需要 |
| `models/pose_landmarker_lite.task` | 人体关键点模型 | 需要 |
| `models/face_landmarker.task` | 人脸关键点模型 | 需要 |
| `demo_camera.py` | A独立调试：打开摄像头、显示画面与状态、处理校准按键 | 不直接作为正式UI使用 |
| `example_for_b.py` | 后台调用方式示例；不是完整后台程序 | 参考，需检查是否仍使用旧合并字段 |
| `tests/test_vision.py`（若保留） | 使用模拟数据检查几何、校准及接口 | 建议保留并补测新规则 |
| `requirements.txt`（若保留） | 起步依赖列表 | 已有环境可不重复安装 |
| `requirements-vision.txt` | A在实际可运行环境导出的依赖版本 | 需要 |
| `README.md` | 本交接说明；下载后可将文件重命名为README.md | 需要 |

不要发送整个venv。B使用自己的虚拟环境安装依赖。

## 2. 各函数有什么功能

### vision/measurements.py

| 类或函数 | 功能 |
| --- | --- |
| `VisionConfig` | 保存肩部、头部、耳—肩比率、距离阈值，以及置信度和校准参数 |
| `VisionConfig.__post_init__()` | 创建配置时校验参数，拒绝非有限值、非正阈值等错误设置 |
| `pixel_point(landmark, width, height, confidence=None)` | 检查关键点坐标、出界和可见性；将归一化坐标转成图像像素坐标，失败返回None |
| `pose_features(landmarks, width, height, confidence)` | 使用鼻子0、双肩11/12，输出肩线角度、鼻子相对肩中点的x/y位置及绘图点 |
| `ear_shoulder_ratio(landmarks, width, height, confidence)` | 使用双耳7/8、双肩11/12，输出耳—肩水平距离比率；关键点不足或肩宽太小时返回None |
| `face_features(landmarks, width, height)` | 计算人脸侧点234/454的归一化水平宽度，并检查出界、过小和粗略正脸条件 |
| `Calibration.__init__(config)` | 初始化一组校准状态、有效时长和采样容器 |
| `Calibration.start(now, reference=None)` | 清空旧样本，开始一次校准；距离校准额外记录参考距离 |
| `Calibration.add(values, now, tolerances)` | 逐帧累计有效时间和样本；检查稳定性、超时，成功时返回各特征的中位数 |
| `Calibration.info()` | 返回校准状态、进度、有效时长、样本数和提示消息，供界面展示 |

这里的像素坐标指摄像头图像坐标，不是桌面屏幕坐标。

### vision/detector.py

| PostureDetector的方法 | 功能 |
| --- | --- |
| `__init__(model_dir=None, config=None)` | 初始化人体与人脸模型、时间戳及两组校准器；默认模型目录为项目根目录的models |
| `update_settings(**settings)` | 更新允许运行中修改的阈值与置信度；不允许运行中修改校准采样参数 |
| `start_posture_calibration()` | 清除旧坐姿基准，开始新的坐姿采样 |
| `start_distance_calibration(known_distance_cm=60.0)` | 清除旧距离基准，按用户量好的参考距离开始采样 |
| `reset_calibration()` | 清除坐姿与距离两类基准 |
| `detect(frame)` | 处理一帧uint8、H×W×3、BGR图像，执行推理、采样和当前帧分类；返回字典，不修改输入图像 |
| `close()` | 释放模型资源；可重复调用 |
| `__enter__()` | 支持with语句，返回检测器实例 |
| `__exit__(*args)` | 离开with时调用close，异常退出也释放模型 |

### 演示、示例与测试

| 函数 | 功能 |
| --- | --- |
| `demo_camera.number(value, digits=2)` | 格式化数字；None显示为-- |
| `demo_camera.main()` | 读取启动参数、打开摄像头、循环detect、画关键点与状态面板、响应P/D/R/Q并释放摄像头 |
| `example_for_b.main()` | 演示外部如何创建、调用、关闭检测器；B需加入自己的线程、队列和规则 |
| 测试辅助`point/poses/faces` | 生成模拟关键点，避免测试必须依赖真实摄像头 |
| 测试辅助`mock_detector` | 构造模拟模型输出的检测器 |
| 测试中的`setUp/detect_at/calibrate` | 准备测试实例、模拟指定时间的检测、辅助完成校准 |
| `test_*`测试方法 | 检查几何方向、低置信度、人脸门控、校准计时、稳定性与超时、接口和配置等行为 |

测试文件若仍是原版，只能代表原先规则的覆盖范围，不能据此宣称新增驼背及拆分规则已验证。

## 3. 当前具体判定规则

### 肩部倾斜：Shoulder bad

使用双肩连线与水平线的夹角。按图像从左到右排序后计算，角度正值表示画面右侧肩点更低。

`肩角变化 = 当前肩线角度 - 校准肩线角度`

当`abs(肩角变化) > shoulder_threshold_deg`时，`shoulder_abnormal=True`，默认8度。

### 头部左右偏移：Head bad

鼻子相对双肩中点的水平位置除以当前肩宽，再减去校准时的同类值，得到`head_dx`。

当`abs(head_dx) > head_threshold_ratio`时，`head_abnormal=True`，默认0.15，即肩宽的15%。左右都能触发；向下偏移不再单独触发Head bad。

### 疑似驼背：Hunch bad

保留以下两个条件，任意一个明确异常即可触发：

1. **头部向下偏移**：`head_dy > head_threshold_ratio`。其中head_dy是鼻子相对肩中点的归一化纵向位置减去校准值。图像y轴向下，因此正偏移代表相对肩膀下降；抬头不触发此条件。
2. **耳—肩水平距离比率**：同侧左耳到左肩、右耳到右肩的水平距离取绝对值后求平均，再除以当前双肩像素距离。比率超过`hunchback_threshold_ratio`即异常，默认0.40。

两项都在坐姿校准完成后启用。头部下移与校准值比较；耳—肩比率仍直接与固定阈值比较，没有减去校准时的耳—肩比率。

`hunchback_abnormal`合并规则：任意一项True→True；两项均False→False；其余情况→None。比如耳朵不可见但头部下移明确异常，仍可输出True；头部未下移但耳朵不可见，则输出None。

`head_down_abnormal`和`ear_shoulder_abnormal`分别说明由哪项触发；两项都True也只算同一类Hunch bad，B不要因此重复记两次。

这是二维关键点的实验性姿态提示，尤其正面视角下不能可靠确诊驼背，也没有测量真正的前倾角。阈值须通过实际用户和摄像头测试调整。

### 距离过近：Too close

`估算距离 = 参考距离 × 校准脸宽比例 / 当前脸宽比例`

低于`min_distance_cm`时返回`too_close=True`，默认50cm。这是面部到摄像头的大致距离，不是严格的眼睛到屏幕距离。须为同一用户、固定镜头、无数字变焦，脸大致朝前。

### 阈值修改位置

在`vision/measurements.py`的`VisionConfig`中：

```python
shoulder_threshold_deg: float = 8.0
head_threshold_ratio: float = 0.15
hunchback_threshold_ratio: float = 0.40
min_distance_cm: float = 50.0
```

前三项越小越敏感；距离阈值越大越容易触发过近。左右偏移与向下偏移目前共用head_threshold_ratio。修改默认值后重启并重新校准。

## 4. 运行与校准

在PyCharm选择`D:\aaa\venv\Scripts\python.exe`，在项目根目录PowerShell执行：

```powershell
.\venv\Scripts\python.exe demo_camera.py
# 若需要DSHOW后端：
.\venv\Scripts\python.exe demo_camera.py --backend dshow --camera 0 --reference-cm 60
```

如果设备编号为1，修改camera参数。关闭其他占用摄像头的软件。

- P：用户端坐，开始坐姿校准。默认累计3秒有效数据且至少20个样本，ready才算完成。
- D：在尺量的参考距离、正脸保持时，开始距离校准。默认参考距离60cm，是镜头到面部的大致距离。
- R：清除两类校准。
- Q/ESC或关闭窗口：退出并释放资源。

校准并不自动验证端坐是否正确。有效时长按相邻有效帧累计；无效帧不计时，超过0.5秒的间隔不计时。不稳定时清空重采；20秒超时后按键重试。

校准只保存在当前实例中，退出后需要重做。分辨率改变会自动清除基准；更换用户、移动摄像头、裁剪、变焦或改变镜像策略后应手动重做。

演示面板分别显示Shoulder bad、Head bad、Hunch bad、Too close，另可显示Down bad和Ear ratio bad辅助调试。True为当前异常，False为当前正常，None为无法判断。面板高度建议按`30 * len(lines) + 20`分配，防止文字被裁掉。

## 5. 返回结果：B应读取哪些字段

| 字段 | 含义与使用方式 |
| --- | --- |
| `shoulder_abnormal` | 肩部倾斜当前帧分类 |
| `head_abnormal` | 头部左右偏移当前帧分类 |
| `hunchback_abnormal` | 头部下移或耳—肩比率异常的合并分类 |
| `head_down_abnormal` | 头部向下偏移子条件 |
| `ear_shoulder_abnormal` | 耳—肩比率子条件 |
| `too_close` | 当前是否距离过近 |
| `posture_abnormal` | 仅肩部或头部左右偏移的旧合并字段，不包括Hunch bad |
| `overall_posture_abnormal` | 肩部、头部左右、Hunch bad三项合并；不包括距离过近 |
| `posture_evaluable` | 鼻子/肩膀特征有效且完成坐姿校准；用于肩部和头部左右判定 |
| `hunchback_evaluable` | 合并后的Hunch bad有明确结果；不能直接用posture_evaluable代替 |
| `distance_evaluable` | 人脸测距特征有效且完成距离校准 |
| `head_relative_position` | 鼻子相对肩中点的{x,y}，单位为肩宽 |
| `head_offset_from_baseline` | 相对坐姿校准的{x,y}变化；无效为None |
| `head_shift_ratio` | 二维偏移总长度，仅保留观察，不再用于Head bad判定 |
| `shoulder_tilt_deg / shoulder_delta_deg` | 当前肩角 / 相对校准角的变化 |
| `hunchback_ratio` | 当前耳—肩水平距离比率；无效为None |
| `estimated_distance_cm` | 估计距离；界面应显示“约xx厘米” |
| `face_width_px / face_width_ratio` | 有效人脸宽度像素值 / 相对图像宽度的比例 |
| `pose_detected / face_detected` | 模型返回关键点；不等于通过质量检查 |
| `posture_landmarks_valid / distance_landmarks_valid` | 鼻子肩膀特征 / 测距特征是否有效 |
| `tracking_valid` | 上述两类特征至少一类有效，不能当作所有检测项均有效 |
| `posture_calibrated / distance_calibrated` | 对应校准基准是否存在 |
| `posture_calibration / distance_calibration` | state、progress、valid_seconds、samples、message |
| `timestamp_ms` | 实例相对时间戳，用于模型和顺序；不是日期时间 |
| `reasons` | 未校准、缺失关键点、画面尺寸变化等原因代码 |
| `points` | 绘图用图像像素坐标；pose/face内关键点索引是字符串 |

所有字段可JSON序列化。分类使用True/False/None三态。合并分类只有任一明确True才True，全部明确False才False，其余None。

不要用`if not flag`代表正常，因为None也会进入该分支；要用`flag is False`。耳朵缺失时reasons可以提示耳肩特征无效，但不代表肩部、头部左右和距离也全部无效。

## 6. B如何接入

### 生命周期和线程

B在自己的摄像头后台线程中创建检测器，循环送帧，停止时关闭。不要每帧新建，不要跨线程同时操作同一个实例。C的界面只发命令，B通过命令队列在检测线程处理校准、配置和停止命令。

```python
from vision import PostureDetector, VisionConfig

# 以下片段放在B的后台线程中；frame和命令队列由B提供。
with PostureDetector(config=VisionConfig(
    shoulder_threshold_deg=8.0,
    head_threshold_ratio=0.15,
    hunchback_threshold_ratio=0.40,
    min_distance_cm=50.0,
)) as detector:
    # 在摄像头循环里，每取得一帧调用一次：
    result = detector.detect(frame)

    flags = {
        'shoulder': result['shoulder_abnormal']
                    if result['posture_evaluable'] else None,
        'head': result['head_abnormal']
                if result['posture_evaluable'] else None,
        'hunchback': result['hunchback_abnormal']
                    if result['hunchback_evaluable'] else None,
        'too_close': result['too_close']
                     if result['distance_evaluable'] else None,
    }
    # B将flags送入自己的持续时间规则，将result送给界面。
```

这是接口片段，不是可直接运行的完整摄像头程序。正式B后台不需要导入demo_camera，也不要启动A的演示窗口。

### 校准及设置命令

用户准备好后，B收到一次命令就调用一次：

```python
detector.start_posture_calibration()
detector.start_distance_calibration(known_distance_cm=60.0)
# 清空时：
detector.reset_calibration()
```

两个start不能在每帧循环里反复调用，否则永远重启校准。调用后继续detect才能完成采样；B把返回的进度发给C显示。

设置变更时在同一检测线程调用：

```python
detector.update_settings(
    shoulder_threshold_deg=8.0,
    head_threshold_ratio=0.15,
    hunchback_threshold_ratio=0.40,
    min_distance_cm=50.0,
    landmark_confidence=0.6,
)
```

配置JSON由B读写，A不会自动保存。用户改变规则阈值或重校准时，B应清除相关连续计时，避免混用修改前后的时间。

## 7. B还要完成什么

| B的任务 | 具体要求 |
| --- | --- |
| 摄像头与后台 | 读取摄像头，检查空帧，保持主界面响应，停止时release摄像头并close检测器 |
| 命令与结果传递 | 用队列传校准、设置、停止命令；向C传结果和画面。队列应有界，画面滞后时丢弃旧帧 |
| 连续异常5秒 | 肩部、头部左右、Hunch bad、距离过近分别计时；明确True才累计，False或None清零。采集/推理中断和过长帧间隔也中断计时，不能将断流期间当作持续异常 |
| 冷却与恢复 | 同一异常持续存在时按设定间隔提醒，避免每帧报警；约定恢复后何时允许新事件 |
| 提醒请求 | 满足持续时间和冷却条件后通知C，C负责弹窗、音效或语音 |
| 事件记录 | 记录异常类型、开始和结束时间、持续时长、触发原因；一段连续异常作为一个事件，避免每帧插入数据库 |
| 时间体系 | 持续计时使用time.monotonic；数据库日期时间另取实际时间，不把timestamp_ms当Unix时间 |
| 设置存储 | 维护config.json，读取阈值、提醒频率、语音开关等；检测相关设置传给A |
| 久坐和番茄钟 | 独立实现45分钟工作/5分钟休息；摄像头短暂识别不到人不应直接当作已休息 |
| 故障处理 | 捕获模型缺失、摄像头断开、非法帧和推理异常；通知界面并停止或恢复，不得显示成正常 |
| 数据交接 | 给D提供统计查询接口或数据表约定，给C提供稳定字段和状态 |

B不要对overall_posture_abnormal单独累计一次，同时又对三种类型分别重复记录。建议以具体类型为事件单位，总合并字段仅用于界面总状态。

A不提供5秒防抖、冷却、音频、弹窗、数据库、跨启动基准保存，也不上传视频。总集成由小组共同联调，D组织测试与交付检查，B不独自承担总集成。

## 8. 验收和交接清单

原版自动测试的历史通过结果不能证明本轮修改已通过。请在实际更新后的项目运行已有测试并补充新规则用例：

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

建议A与D逐项确认：

- 校准前分类为None，P/D分别进入ready；摄像头画面正常。
- 仅左右移头时Head bad变化；若耳肩指标也变化，允许同时出现Hunch bad，不能强求分类互斥。
- 向下偏移超过阈值时Down bad=True，即使左右偏移不超阈值，Hunch bad也应True。
- 只有耳肩比率超阈值时Ear ratio bad=True、Hunch bad=True。
- 向上偏移不触发Down bad；恰好等于阈值不触发，因为代码使用大于号。
- 头部下移异常且耳朵丢失时Hunch bad仍True；下移正常但耳朵丢失时Hunch bad为None。
- 肩部、头部、距离的有效性独立处理；丢失关键点不沿用旧值。
- 40/50/70cm等位置记录距离误差；正常端坐30秒检查误判。
- B侧异常不足5秒不提醒，连续超过5秒才提醒；肩部3秒加头部2秒不能拼接成5秒。
- 关闭界面和后台后摄像头释放。

本说明未宣称已完成真实模型或本轮新增规则测试，须以你们本机结果为准。

环境确认可运行后，在项目根目录导出：

```powershell
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m pip freeze > requirements-vision.txt
```

A交给B：vision目录、两个模型、requirements-vision.txt、本说明、调试demo、人工验收结果；模型和源码放在同一约定目录。Python版本先统一为A已跑通的3.11，具体依赖以本机导出为准。

参考文档：

- 人体模型接口：https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python
- 人脸模型接口：https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python

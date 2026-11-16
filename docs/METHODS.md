# How RodentTrack works (and text for your Methods section)

**English** · 中文说明见下方

## Pipeline

1. **Geometry.** The user marks the four corners of the arena floor. A perspective transform maps image pixels to centimetres, so a tilted camera is corrected and all distances and zones are in cm.
2. **Background.** `bg_frames` (default 50) frames spread over the analysed period are combined by a per-pixel median. Because the animal moves, it is absent from the median; fixed glare, objects and cages remain in it.
3. **Detection.** Each frame (downscaled to `proc_width`, default 960 px) is blurred and subtracted from the background (brighter, darker or both, depending on the animal colour). The difference is thresholded, cleaned by morphological opening/closing, restricted to the arena minus exclusion zones (and minus cage interiors), and the largest blob within the allowed area range (cm²) is taken as the animal. The threshold can be set automatically: candidate thresholds are scored by the fraction of sampled frames with exactly one dominant blob of plausible size, and the middle of the best plateau is chosen.
4. **Body centre, nose and tail.** The body centre is the centroid of the blob after removing the tail with an opening of `body_open_cm`. The two ends of the body axis are candidate nose positions; the nose is chosen from the direction of movement, the end where the thin tail leaves the body, and continuity with the previous frame.
5. **Smoothing.** Gaps up to `max_gap_frames` are interpolated and the track is median-filtered over `smooth_frames`.
6. **Exploration.** A frame counts as exploration of a zone when the nose is inside the contact zone (object outline enlarged by `interaction_cm`; default 2 cm for objects, 3 cm for wire cages) **and** the body centre is not on the object (climbing is reported separately). Optionally the head must point at the zone within `heading_deg`. Bouts shorter than `min_bout_s` (0.2 s) are removed and bouts separated by less than `merge_gap_s` (0.2 s) are merged. Exploration time, number of bouts, first-contact latency and mean bout duration are reported per zone.
7. **Other measures.** Distance and speed from the smoothed body centre (cm); centre time and entries (centre square = `center_ratio` of the side); immobility (speed < 2 cm/s for ≥ 1 s); zone time and entries for the body centre; discrimination index DI = (B − A) / (B + A).

## Suggested Methods text

> Behaviour was scored from top-view videos with RodentTrack v1.0.1 (https://doi.org/10.5281/zenodo.24279287), an open-source Python/OpenCV tool. The arena floor corners were marked to correct for camera perspective and convert positions to centimetres. The animal was detected in every frame by median-background subtraction and the body centre and nose were estimated from the animal’s silhouette. Object exploration was defined as the nose being within 2 cm of the object (3 cm of the wire cage) while the body centre was not on the object; bouts shorter than 0.2 s were discarded and bouts separated by less than 0.2 s were merged. The discrimination index was calculated as (novel − familiar) / (novel + familiar) exploration time. Detection rate exceeded 95 % in all analysed videos, and tracking was checked visually on the annotated output video. Videos were analysed with file names coded so that the experimenter was blind to group.

Adjust the numbers to the settings you actually used (they are stored in each config file), report the detection rate you obtained, and keep the blinding sentence only if it is true for your study.

---

## 中文：论文方法部分可参考的写法

> 行为视频（俯拍）使用开源软件 RodentTrack v1.0.1（Python / OpenCV，https://doi.org/10.5281/zenodo.24279287）分析。在视频画面上标记场地底面四角，进行透视校正并将坐标换算为厘米。采用中位数背景相减法逐帧检测动物，并根据轮廓估计身体中心和鼻尖位置。物体探索定义为鼻尖位于物体外 2 cm（网笼外 3 cm）范围内且身体中心不在物体上；短于 0.2 s 的接触不计，间隔小于 0.2 s 的接触合并。辨别指数 = (新物体 − 熟悉物体) / (新物体 + 熟悉物体) 探索时间。所有视频的检测率均 > 95%，并通过标注视频目视核对追踪结果。

请按实际使用的参数（保存在配置文件里）修改数字，写上实际得到的检测率；盲法那句只有在你的实验确实做到时再写。

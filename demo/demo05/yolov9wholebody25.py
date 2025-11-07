#!/usr/bin/env python
# -*- coding: utf-8 -*-
import copy
from dataclasses import dataclass

import cv2
import numpy as np
from typing import List, Tuple, Any


@dataclass(frozen=False)
class Box():
    classid: int
    score: float
    x1: int
    y1: int
    x2: int
    y2: int
    cx: int
    cy: int
    generation: int = -1  # -1: Unknown, 0: Adult, 1: Child
    gender: int = -1  # -1: Unknown, 0: Male, 1: Female
    handedness: int = -1  # -1: Unknown, 0: Left, 1: Right
    head_pose: int = -1  # -1: Unknown, 0: Front, 1: Right-Front, 2: Right-Side, 3: Right-Back, 4: Back, 5: Left-Back, 6: Left-Side, 7: Left-Front
    is_used: bool = False


def preprocess(
    image: np.ndarray,
    model_input_size: Tuple[int, int],
) -> np.ndarray:
    """
    Preprocess an input image for model inference.
    
    Args:
        image (np.ndarray): Input image in BGR format.
        
    Returns:
        np.ndarray: Preprocessed image as a NumPy array in NCHW format.
    """
    input_image: np.ndarray = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    input_image = cv2.resize(input_image, model_input_size)
    # input_image = input_image.astype(np.float32) / 1.0
    input_image = input_image.astype(np.float32) / 255.0
    input_image = np.transpose(input_image, (2, 0, 1))  # Change to (C, H, W)
    input_image = np.expand_dims(input_image, axis=0)  # Add batch dimension

    return input_image


def postprocess_nms(
    outputs: np.ndarray,
    original_image_size: Tuple[int, int],
    model_input_size: Tuple[int, int],
    score_th: float = 0.3,
    nms_th: float = 0.3,
) -> np.ndarray:
    """
    Postprocess the model outputs using Non-Maximum Suppression (NMS).
    
    Args:
        outputs (np.ndarray): Model raw outputs.
        original_image_size (Tuple[int, int]): Original image width and height.
        model_input_size (Tuple[int, int]): Model input width and height.
        score_th (float): Score threshold for filtering boxes.
        nms_th (float): IoU threshold for NMS.
        
    Returns:
        np.ndarray: Final filtered bounding boxes after NMS.
    """
    outputs = outputs[0]

    # Bbox と scores
    bboxes: np.ndarray = outputs[0:4, :].T
    scores: np.ndarray = outputs[4:, :].T

    # cxcywh から xyxy に変換
    bboxes[:, 0] = bboxes[:, 0] - bboxes[:, 2] / 2  # x1 = cx - w/2
    bboxes[:, 1] = bboxes[:, 1] - bboxes[:, 3] / 2  # y1 = cy - h/2
    bboxes[:, 2] = bboxes[:, 0] + bboxes[:, 2]  # x2 = x1 + w
    bboxes[:, 3] = bboxes[:, 1] + bboxes[:, 3]  # y2 = y1 + h

    # 各クラスごとのスコアとクラスIDを取得
    class_ids: np.ndarray = np.argmax(scores, axis=1)  # (6300,)
    confidences: np.ndarray = np.max(scores, axis=1)  # (6300,)

    # 信頼度スコアでフィルタリング
    valid_indices: np.ndarray = np.where(confidences > score_th)[0]
    filtered_boxes: np.ndarray = bboxes[valid_indices]
    filtered_scores: np.ndarray = confidences[valid_indices]
    filtered_class_ids: np.ndarray = class_ids[valid_indices]

    # NMS
    indices: List[int] = cv2.dnn.NMSBoxesBatched(  # type: ignore
        filtered_boxes.tolist(),
        filtered_scores.tolist(),
        filtered_class_ids.tolist(),
        score_th,
        nms_th,
    )
    final_boxes: List[np.ndarray] = []
    if len(indices) > 0:
        indices = indices.tolist()  # type: ignore
        for idx in indices:
            box: np.ndarray = filtered_boxes[idx].astype(np.float32)
            box[0::2] *= original_image_size[0] / model_input_size[0]
            box[1::2] *= original_image_size[1] / model_input_size[1]
            box = box.astype(np.int64).tolist()
            final_boxes.append(
                np.array([
                    0,  # Placeholder for future usage (e.g., batch ID)
                    filtered_class_ids[idx],
                    filtered_scores[idx],
                    *box,
                ]))

    return np.array(final_boxes)


def postprocess_subclass(
    image: np.ndarray,
    obj_class_score_th,
    attr_class_score_th,
    boxes: np.ndarray,
    disable_generation_identification_mode: bool,
    disable_gender_identification_mode: bool,
    disable_left_and_right_hand_identification_mode: bool,
    disable_headpose_identification_mode: bool,
) -> List[Box]:
    image_height = image.shape[0]
    image_width = image.shape[1]

    result_boxes: List[Box] = []

    if len(boxes) > 0:
        scores = boxes[:, 2:3]
        keep_idxs = scores[:, 0] > obj_class_score_th
        scores_keep = scores[keep_idxs, :]
        boxes_keep = boxes[keep_idxs, :]

        if len(boxes_keep) > 0:
            # Object filter
            for box, score in zip(boxes_keep, scores_keep):
                classid = int(box[1])
                x_min = int(max(0, box[3]))
                y_min = int(max(0, box[4]))
                x_max = int(min(box[5], image_width))
                y_max = int(min(box[6], image_height))
                cx = (x_min + x_max) // 2
                cy = (y_min + y_max) // 2
                result_boxes.append(
                    Box(
                        classid=classid,
                        score=float(score),
                        x1=x_min,
                        y1=y_min,
                        x2=x_max,
                        y2=y_max,
                        cx=cx,
                        cy=cy,
                        generation=-1,  # -1: Unknown, 0: Adult, 1: Child
                        gender=-1,  # -1: Unknown, 0: Male, 1: Female
                        handedness=-1,  # -1: Unknown, 0: Left, 1: Right
                        head_pose=
                        -1,  # -1: Unknown, 0: Front, 1: Right-Front, 2: Right-Side, 3: Right-Back, 4: Back, 5: Left-Back, 6: Left-Side, 7: Left-Front
                    ))
            # Attribute filter
            result_boxes = [
                box for box in result_boxes \
                    if (box.classid in [1,2,3,4,8,9,10,11,12,13,14,15] and box.score >= attr_class_score_th) or box.classid not in [1,2,3,4,8,9,10,11,12,13,14,15]
            ]

            # Adult, Child merge
            # classid: 0 -> Body
            #   classid: 1 -> Adult
            #   classid: 2 -> Child
            # 1. Calculate Adult and Child IoUs for Body detection results
            # 2. Connect either the Adult or the Child with the highest score and the highest IoU with the Body.
            # 3. Exclude Adult and Child from detection results
            if not disable_generation_identification_mode:
                body_boxes = [box for box in result_boxes if box.classid == 0]
                generation_boxes = [
                    box for box in result_boxes if box.classid in [1, 2]
                ]
                find_most_relevant_obj(base_objs=body_boxes,
                                       target_objs=generation_boxes)
            result_boxes = [
                box for box in result_boxes if box.classid not in [1, 2]
            ]
            # Male, Female merge
            # classid: 0 -> Body
            #   classid: 3 -> Male
            #   classid: 4 -> Female
            # 1. Calculate Male and Female IoUs for Body detection results
            # 2. Connect either the Male or the Female with the highest score and the highest IoU with the Body.
            # 3. Exclude Male and Female from detection results
            if not disable_gender_identification_mode:
                body_boxes = [box for box in result_boxes if box.classid == 0]
                gender_boxes = [
                    box for box in result_boxes if box.classid in [3, 4]
                ]
                find_most_relevant_obj(base_objs=body_boxes,
                                       target_objs=gender_boxes)
            result_boxes = [
                box for box in result_boxes if box.classid not in [3, 4]
            ]
            # HeadPose merge
            # classid: 7 -> Head
            #   classid:  8 -> Front
            #   classid:  9 -> Right-Front
            #   classid: 10 -> Right-Side
            #   classid: 11 -> Right-Back
            #   classid: 12 -> Back
            #   classid: 13 -> Left-Back
            #   classid: 14 -> Left-Side
            #   classid: 15 -> Left-Front
            # 1. Calculate HeadPose IoUs for Head detection results
            # 2. Connect either the HeadPose with the highest score and the highest IoU with the Head.
            # 3. Exclude HeadPose from detection results
            if not disable_headpose_identification_mode:
                head_boxes = [box for box in result_boxes if box.classid == 7]
                headpose_boxes = [
                    box for box in result_boxes
                    if box.classid in [8, 9, 10, 11, 12, 13, 14, 15]
                ]
                find_most_relevant_obj(base_objs=head_boxes,
                                       target_objs=headpose_boxes)
            result_boxes = [
                box for box in result_boxes
                if box.classid not in [8, 9, 10, 11, 12, 13, 14, 15]
            ]
            # Left and right hand merge
            # classid: 21 -> Hand
            #   classid: 22 -> Left-Hand
            #   classid: 23 -> Right-Hand
            # 1. Calculate Left-Hand and Right-Hand IoUs for Hand detection results
            # 2. Connect either the Left-Hand or the Right-Hand with the highest score and the highest IoU with the Hand.
            # 3. Exclude Left-Hand and Right-Hand from detection results
            if not disable_left_and_right_hand_identification_mode:
                hand_boxes = [box for box in result_boxes if box.classid == 21]
                left_right_hand_boxes = [
                    box for box in result_boxes if box.classid in [22, 23]
                ]
                find_most_relevant_obj(base_objs=hand_boxes,
                                       target_objs=left_right_hand_boxes)
            result_boxes = [
                box for box in result_boxes if box.classid not in [22, 23]
            ]
    return result_boxes


def find_most_relevant_obj(
    *,
    base_objs: List[Box],
    target_objs: List[Box],
):
    for base_obj in base_objs:
        most_relevant_obj: Any = None
        best_score = 0.0
        best_iou = 0.0
        best_distance = float('inf')

        for target_obj in target_objs:
            distance = ((base_obj.cx - target_obj.cx)**2 +
                        (base_obj.cy - target_obj.cy)**2)**0.5
            # Process only unused objects with center Euclidean distance less than or equal to 10.0
            if not target_obj.is_used and distance <= 10.0:
                # Prioritize high-score objects
                if target_obj.score >= best_score:
                    # IoU Calculation
                    iou: float = \
                        calculate_iou(
                            base_obj=base_obj,
                            target_obj=target_obj,
                        )
                    # Adopt object with highest IoU
                    if iou > best_iou:
                        most_relevant_obj = target_obj
                        best_iou = iou
                        # Calculate the Euclidean distance between the center coordinates
                        # of the base and the center coordinates of the target
                        best_distance = distance
                        best_score = target_obj.score
                    elif iou > 0.0 and iou == best_iou:
                        # Calculate the Euclidean distance between the center coordinates
                        # of the base and the center coordinates of the target
                        if distance < best_distance:
                            most_relevant_obj = target_obj
                            best_distance = distance
                            best_score = target_obj.score
        if most_relevant_obj:
            if most_relevant_obj.classid == 1:
                base_obj.generation = 0
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 2:
                base_obj.generation = 1
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 3:
                base_obj.gender = 0
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 4:
                base_obj.gender = 1
                most_relevant_obj.is_used = True

            elif most_relevant_obj.classid == 8:
                base_obj.head_pose = 0
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 9:
                base_obj.head_pose = 1
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 10:
                base_obj.head_pose = 2
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 11:
                base_obj.head_pose = 3
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 12:
                base_obj.head_pose = 4
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 13:
                base_obj.head_pose = 5
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 14:
                base_obj.head_pose = 6
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 15:
                base_obj.head_pose = 7
                most_relevant_obj.is_used = True

            elif most_relevant_obj.classid == 22:
                base_obj.handedness = 0
                most_relevant_obj.is_used = True
            elif most_relevant_obj.classid == 23:
                base_obj.handedness = 1
                most_relevant_obj.is_used = True


def calculate_iou(
    *,
    base_obj: Box,
    target_obj: Box,
) -> float:
    # Calculate areas of overlap
    inter_xmin = max(base_obj.x1, target_obj.x1)
    inter_ymin = max(base_obj.y1, target_obj.y1)
    inter_xmax = min(base_obj.x2, target_obj.x2)
    inter_ymax = min(base_obj.y2, target_obj.y2)
    # If there is no overlap
    if inter_xmax <= inter_xmin or inter_ymax <= inter_ymin:
        return 0.0
    # Calculate area of overlap and area of each bounding box
    inter_area = (inter_xmax - inter_xmin) * (inter_ymax - inter_ymin)
    area1 = (base_obj.x2 - base_obj.x1) * (base_obj.y2 - base_obj.y1)
    area2 = (target_obj.x2 - target_obj.x1) * (target_obj.y2 - target_obj.y1)
    # Calculate IoU
    iou = inter_area / float(area1 + area2 - inter_area)
    return iou


def draw_dashed_line(
    image: np.ndarray,
    pt1: Tuple[int, int],
    pt2: Tuple[int, int],
    color: Tuple[int, int, int],
    thickness: int = 1,
    dash_length: int = 10,
):
    """Function to draw a dashed line"""
    dist = ((pt1[0] - pt2[0])**2 + (pt1[1] - pt2[1])**2)**0.5
    dashes = int(dist / dash_length)
    for i in range(dashes):
        start = [
            int(pt1[0] + (pt2[0] - pt1[0]) * i / dashes),
            int(pt1[1] + (pt2[1] - pt1[1]) * i / dashes)
        ]
        end = [
            int(pt1[0] + (pt2[0] - pt1[0]) * (i + 0.5) / dashes),
            int(pt1[1] + (pt2[1] - pt1[1]) * (i + 0.5) / dashes)
        ]
        cv2.line(image, tuple(start), tuple(end), color, thickness)


def draw_dashed_rectangle(image: np.ndarray,
                          top_left: Tuple[int, int],
                          bottom_right: Tuple[int, int],
                          color: Tuple[int, int, int],
                          thickness: int = 1,
                          dash_length: int = 10):
    """Function to draw a dashed rectangle"""
    tl_tr = (bottom_right[0], top_left[1])
    bl_br = (top_left[0], bottom_right[1])
    draw_dashed_line(image, top_left, tl_tr, color, thickness, dash_length)
    draw_dashed_line(image, tl_tr, bottom_right, color, thickness, dash_length)
    draw_dashed_line(image, bottom_right, bl_br, color, thickness, dash_length)
    draw_dashed_line(image, bl_br, top_left, color, thickness, dash_length)


BOX_COLORS = [
    [(216, 67, 21), "Front"],
    [(255, 87, 34), "Right-Front"],
    [(123, 31, 162), "Right-Side"],
    [(255, 193, 7), "Right-Back"],
    [(76, 175, 80), "Back"],
    [(33, 150, 243), "Left-Back"],
    [(156, 39, 176), "Left-Side"],
    [(0, 188, 212), "Left-Front"],
]


def draw_debug(
    image: np.ndarray,
    boxes: List[Box],
    disable_render_classids: List[int],
    disable_gender_identification_mode: bool,
    disable_left_and_right_hand_identification_mode: bool,
    disable_headpose_identification_mode: bool,
) -> np.ndarray:
    debug_image = copy.deepcopy(image)
    debug_image_w = debug_image.shape[1]

    white_line_width = 2
    colored_line_width = white_line_width - 1

    for box in boxes:
        classid: int = box.classid
        color: Tuple[int, int, int] = (255, 255, 255)

        if classid in disable_render_classids:
            continue

        if classid == 0:
            # Body
            if not disable_gender_identification_mode:
                # Body
                if box.gender == 0:
                    # Male
                    color = (255, 0, 0)
                elif box.gender == 1:
                    # Female
                    color = (139, 116, 225)
                else:
                    # Unknown
                    color = (0, 200, 255)
            else:
                # Body
                color = (0, 200, 255)
        elif classid == 5:
            # Body-With-Wheelchair
            color = (0, 200, 255)
        elif classid == 6:
            # Body-With-Crutches
            color = (83, 36, 179)
        elif classid == 7:
            # Head
            if not disable_headpose_identification_mode:
                color = BOX_COLORS[
                    box.head_pose][0] if box.head_pose != -1 else (
                        216, 67, 21)  # type:ignore
            else:
                color = (0, 0, 255)
        elif classid == 16:
            # Face
            color = (0, 200, 255)
        elif classid == 17:
            # Eye
            color = (255, 0, 0)
        elif classid == 18:
            # Nose
            color = (0, 255, 0)
        elif classid == 19:
            # Mouth
            color = (0, 0, 255)
        elif classid == 20:
            # Ear
            color = (203, 192, 255)
        elif classid == 21:
            if not disable_left_and_right_hand_identification_mode:
                # Hands
                if box.handedness == 0:
                    # Left-Hand
                    color = (0, 128, 0)
                elif box.handedness == 1:
                    # Right-Hand
                    color = (255, 0, 255)
                else:
                    # Unknown
                    color = (0, 255, 0)
            else:
                # Hands
                color = (0, 255, 0)
        elif classid == 24:
            # Foot
            color = (250, 0, 136)

        if (classid == 0 and not disable_gender_identification_mode) \
            or (classid == 7 and not disable_headpose_identification_mode) \
            or (classid == 21 and not disable_left_and_right_hand_identification_mode):

            if classid == 0:
                if box.gender == -1:
                    draw_dashed_rectangle(image=debug_image,
                                          top_left=(box.x1, box.y1),
                                          bottom_right=(box.x2, box.y2),
                                          color=color,
                                          thickness=2,
                                          dash_length=10)
                else:
                    cv2.rectangle(debug_image, (box.x1, box.y1),
                                  (box.x2, box.y2), (255, 255, 255),
                                  white_line_width)
                    cv2.rectangle(debug_image, (box.x1, box.y1),
                                  (box.x2, box.y2), color, colored_line_width)

            elif classid == 7:
                if box.head_pose == -1:
                    draw_dashed_rectangle(image=debug_image,
                                          top_left=(box.x1, box.y1),
                                          bottom_right=(box.x2, box.y2),
                                          color=color,
                                          thickness=2,
                                          dash_length=10)
                else:
                    cv2.rectangle(debug_image, (box.x1, box.y1),
                                  (box.x2, box.y2), (255, 255, 255),
                                  white_line_width)
                    cv2.rectangle(debug_image, (box.x1, box.y1),
                                  (box.x2, box.y2), color, colored_line_width)

            elif classid == 21:
                if box.handedness == -1:
                    draw_dashed_rectangle(image=debug_image,
                                          top_left=(box.x1, box.y1),
                                          bottom_right=(box.x2, box.y2),
                                          color=color,
                                          thickness=2,
                                          dash_length=10)
                else:
                    cv2.rectangle(debug_image, (box.x1, box.y1),
                                  (box.x2, box.y2), (255, 255, 255),
                                  white_line_width)
                    cv2.rectangle(debug_image, (box.x1, box.y1),
                                  (box.x2, box.y2), color, colored_line_width)

        else:
            cv2.rectangle(debug_image, (box.x1, box.y1), (box.x2, box.y2),
                          (255, 255, 255), white_line_width)
            cv2.rectangle(debug_image, (box.x1, box.y1), (box.x2, box.y2),
                          color, colored_line_width)

        # Attributes text
        generation_txt = ''
        if box.generation == -1:
            generation_txt = ''
        elif box.generation == 0:
            generation_txt = 'Adult'
        elif box.generation == 1:
            generation_txt = 'Child'

        gender_txt = ''
        if box.gender == -1:
            gender_txt = ''
        elif box.gender == 0:
            gender_txt = 'M'
        elif box.gender == 1:
            gender_txt = 'F'

        attr_txt = f'{generation_txt}({gender_txt})' if gender_txt != '' else f'{generation_txt}'

        headpose_txt = BOX_COLORS[
            box.head_pose][1] if box.head_pose != -1 else ''
        attr_txt = f'{attr_txt} {headpose_txt}' if headpose_txt != '' else f'{attr_txt}'

        cv2.putText(
            debug_image,
            f'{attr_txt}',
            (box.x1 if box.x1 + 50 < debug_image_w else debug_image_w - 50,
             box.y1 - 10 if box.y1 - 25 > 0 else 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            debug_image,
            f'{attr_txt}',
            (box.x1 if box.x1 + 50 < debug_image_w else debug_image_w - 50,
             box.y1 - 10 if box.y1 - 25 > 0 else 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            1,
            cv2.LINE_AA,
        )

        handedness_txt = ''
        if box.handedness == -1:
            handedness_txt = ''
        elif box.handedness == 0:
            handedness_txt = 'L'
        elif box.handedness == 1:
            handedness_txt = 'R'
        cv2.putText(
            debug_image,
            f'{handedness_txt}',
            (box.x1 if box.x1 + 50 < debug_image_w else debug_image_w - 50,
             box.y1 - 10 if box.y1 - 25 > 0 else 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            debug_image,
            f'{handedness_txt}',
            (box.x1 if box.x1 + 50 < debug_image_w else debug_image_w - 50,
             box.y1 - 10 if box.y1 - 25 > 0 else 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            1,
            cv2.LINE_AA,
        )

        # cv2.putText(
        #     debug_image,
        #     f'{box.score:.2f}',
        #     (
        #         box.x1 if box.x1+50 < debug_image_w else debug_image_w-50,
        #         box.y1-10 if box.y1-25 > 0 else 20
        #     ),
        #     cv2.FONT_HERSHEY_SIMPLEX,
        #     0.7,
        #     (255, 255, 255),
        #     2,
        #     cv2.LINE_AA,
        # )
        # cv2.putText(
        #     debug_image,
        #     f'{box.score:.2f}',
        #     (
        #         box.x1 if box.x1+50 < debug_image_w else debug_image_w-50,
        #         box.y1-10 if box.y1-25 > 0 else 20
        #     ),
        #     cv2.FONT_HERSHEY_SIMPLEX,
        #     0.7,
        #     color,
        #     1,
        #     cv2.LINE_AA,
        # )

    return debug_image

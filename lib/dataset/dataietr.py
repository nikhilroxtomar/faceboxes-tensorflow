


import os
import random
import cv2
import numpy as np
from functools import partial

from lib.helper.logger import logger
from tensorpack.dataflow import DataFromList
from tensorpack.dataflow import BatchData, MultiThreadMapData, MultiProcessPrefetchData


from lib.dataset.augmentor.augmentation import Random_contrast,Random_saturation,\
    Random_brightness,Random_scale_withbbox,Random_flip, Fill_img,baidu_aug,dsfd_aug
from lib.core.model.facebox.training_target_creation import get_training_targets
from train_config import config as cfg


class data_info(object):
    def __init__(self,img_root,txt):
        self.txt_file=txt
        self.root_path = img_root
        self.metas=[]


        self.read_txt()

    def read_txt(self):
        with open(self.txt_file) as _f:
            txt_lines=_f.readlines()
        txt_lines.sort()
        for line in txt_lines:
            line=line.rstrip()

            _img_path=line.rsplit('| ',1)[0]
            _label=line.rsplit('| ',1)[-1]

            current_img_path=os.path.join(self.root_path,_img_path)
            current_img_label=_label
            self.metas.append([current_img_path,current_img_label])

            ###some change can be made here
        logger.info('the dataset contains %d images'%(len(txt_lines)))
        logger.info('the datasets contains %d samples'%(len(self.metas)))


    def get_all_sample(self):
        random.shuffle(self.metas)
        return self.metas


class BaseDataIter():
    def __init__(self,img_root_path='',ann_file=None,training_flag=True):

        self.shuffle=True
        self.training_flag=training_flag

        self.num_gpu = cfg.TRAIN.num_gpu
        self.batch_size = cfg.TRAIN.batch_size
        self.thread_num = cfg.TRAIN.thread_num
        self.process_num = cfg.TRAIN.process_num
        self.buffer_size = cfg.TRAIN.buffer_size
        self.prefetch_size = cfg.TRAIN.prefetch_size


        self.dataset_list = self.parse_file(img_root_path, ann_file)

        self.ds=self.build_iter(self.dataset_list)


    def parse_file(self,im_root_path,ann_file):
        '''
        :return:
        '''
        logger.info("[x] Get dataset from {}".format(im_root_path))

        ann_info = data_info(im_root_path, ann_file)
        all_samples = ann_info.get_all_sample()

        return all_samples


    def build_iter(self,samples):


        map_func=partial(self._map_func,is_training=self.training_flag)
        ds = DataFromList(samples, shuffle=True)

        ds = MultiThreadMapData(ds, self.thread_num, map_func, buffer_size=self.buffer_size)

        ds = BatchData(ds, self.num_gpu *  self.batch_size)
        ds = MultiProcessPrefetchData(ds, self.prefetch_size, self.process_num)
        ds.reset_state()
        ds = ds.get_data()
        return ds

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.ds)


    def _map_func(self,dp,is_training):

        raise NotImplementedError("you need implemented the map func for your data")

    def set_params(self):
        raise NotImplementedError("you need implemented  func for your data")



class FaceBoxesDataIter(BaseDataIter):

    def _map_func(self,dp,is_training):
        fname, annos = dp
        image = cv2.imread(fname, cv2.IMREAD_COLOR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        labels = annos.split(' ')
        boxes = []
        for label in labels:
            bbox = np.array(label.split(','), dtype=np.float)
            ##the anchor need ymin,xmin,ymax,xmax
            boxes.append([bbox[0], bbox[1], bbox[2], bbox[3], 1])

        boxes = np.array(boxes, dtype=np.float)

        ###clip the bbox for the reason that some bboxs are beyond the image
        # h_raw_limit, w_raw_limit, _ = image.shape
        # boxes[:, 3] = np.clip(boxes[:, 3], 0, w_raw_limit)
        # boxes[:, 2] = np.clip(boxes[:, 2], 0, h_raw_limit)
        # boxes[boxes < 0] = 0
        #########random scale
        ############## becareful with this func because there is a Infinite loop in its body
        if is_training:

            sample_dice = random.uniform(0, 1)
            if sample_dice > 0.6 and sample_dice <= 1:
                image, boxes = Random_scale_withbbox(image, boxes, target_shape=[cfg.MODEL.hin, cfg.MODEL.win],
                                                     jitter=0.3)

            if sample_dice > 0.3 and sample_dice <= 0.6:
                boxes_ = boxes[:, 0:4]
                klass_ = boxes[:, 4:]

                image, boxes_, klass_ = dsfd_aug(image, boxes_, klass_)
                if random.uniform(0, 1) > 0.5:
                    image, shift_x, shift_y = Fill_img(image, target_width=cfg.MODEL.win, target_height=cfg.MODEL.hin)
                    boxes_[:, 0:4] = boxes_[:, 0:4] + np.array([shift_x, shift_y, shift_x, shift_y], dtype='float32')
                h, w, _ = image.shape
                boxes_[:, 0] /= w
                boxes_[:, 1] /= h
                boxes_[:, 2] /= w
                boxes_[:, 3] /= h
                interp_methods = [cv2.INTER_LINEAR, cv2.INTER_CUBIC, cv2.INTER_AREA, cv2.INTER_NEAREST,
                                  cv2.INTER_LANCZOS4]
                interp_method = random.choice(interp_methods)
                image = cv2.resize(image, (cfg.MODEL.win, cfg.MODEL.hin), interpolation=interp_method)

                boxes_[:, 0] *= cfg.MODEL.win
                boxes_[:, 1] *= cfg.MODEL.hin
                boxes_[:, 2] *= cfg.MODEL.win
                boxes_[:, 3] *= cfg.MODEL.hin
                image = image.astype(np.uint8)
                boxes = np.concatenate([boxes_, klass_], axis=1)
            else:
                boxes_ = boxes[:, 0:4]
                klass_ = boxes[:, 4:]
                image, boxes_, klass_ = baidu_aug(image, boxes_, klass_)
                if random.uniform(0, 1) > 0.5:
                    image, shift_x, shift_y = Fill_img(image, target_width=cfg.MODEL.win, target_height=cfg.MODEL.hin)
                    boxes_[:, 0:4] = boxes_[:, 0:4] + np.array([shift_x, shift_y, shift_x, shift_y], dtype='float32')
                h, w, _ = image.shape
                boxes_[:, 0] /= w
                boxes_[:, 1] /= h
                boxes_[:, 2] /= w
                boxes_[:, 3] /= h

                interp_methods = [cv2.INTER_LINEAR, cv2.INTER_CUBIC, cv2.INTER_AREA, cv2.INTER_NEAREST,
                                  cv2.INTER_LANCZOS4]
                interp_method = random.choice(interp_methods)
                image = cv2.resize(image, (cfg.MODEL.win, cfg.MODEL.hin), interpolation=interp_method)

                boxes_[:, 0] *= cfg.MODEL.win
                boxes_[:, 1] *= cfg.MODEL.hin
                boxes_[:, 2] *= cfg.MODEL.win
                boxes_[:, 3] *= cfg.MODEL.hin
                image = image.astype(np.uint8)
                boxes = np.concatenate([boxes_, klass_], axis=1)

            if random.uniform(0, 1) > 0.5:
                image, boxes = Random_flip(image, boxes)
            # if random.uniform(0, 1) > 0.5:
            #     image = Pixel_jitter(image, max_=15)
            if random.uniform(0, 1) > 0.5:
                image = Random_brightness(image, 35)
            if random.uniform(0, 1) > 0.5:
                image = Random_contrast(image, [0.5, 1.5])
            if random.uniform(0, 1) > 0.5:
                image = Random_saturation(image, [0.5, 1.5])
            # if random.uniform(0, 1) > 0.5:
            #     a = [3, 5, 7, 9]
            #     k = random.sample(a, 1)[0]
            #     image = Blur_aug(image, ksize=(k, k))
            # if random.uniform(0, 1) > 0.7:
            #     image = Gray_aug(image)
            # if random.uniform(0, 1) > 0.7:
            #     image = Swap_change_aug(image)
            # if random.uniform(0, 1) > 0.7:
            #     boxes_ = boxes[:, 0:4]
            #     klass_ = boxes[:, 4:]
            #     angle = random.sample([-90, 90], 1)[0]
            #     image, boxes_ = Rotate_with_box(image, boxes=boxes_, angle=angle)
            #     boxes = np.concatenate([boxes_, klass_], axis=1)


        else:
            boxes_ = boxes[:, 0:4]
            klass_ = boxes[:, 4:]
            image, shift_x, shift_y = Fill_img(image, target_width=cfg.MODEL.win, target_height=cfg.MODEL.hin)
            boxes_[:, 0:4] = boxes_[:, 0:4] + np.array([shift_x, shift_y, shift_x, shift_y], dtype='float32')
            h, w, _ = image.shape
            boxes_[:, 0] /= w
            boxes_[:, 1] /= h
            boxes_[:, 2] /= w
            boxes_[:, 3] /= h

            image = cv2.resize(image, (cfg.MODEL.win, cfg.MODEL.hin))

            boxes_[:, 0] *= cfg.MODEL.win
            boxes_[:, 1] *= cfg.MODEL.hin
            boxes_[:, 2] *= cfg.MODEL.win
            boxes_[:, 3] *= cfg.MODEL.hin
            image = image.astype(np.uint8)
            boxes = np.concatenate([boxes_, klass_], axis=1)

        ###cove the small faces
        boxes_clean = []
        for i in range(boxes.shape[0]):
            box = boxes[i]

            if (box[3] - box[1]) * (box[2] - box[0]) < cfg.DATA.cover_small_face:
                image[int(box[1]):int(box[3]), int(box[0]):int(box[2]), :] = cfg.DATA.PIXEL_MEAN
            else:
                boxes_clean.append([box[1], box[0], box[3], box[2]])
        boxes = np.array(boxes_clean)
        boxes = boxes / cfg.MODEL.hin

        # for i in range(boxes.shape[0]):
        #     box=boxes[i]
        #     cv2.rectangle(image, (int(box[1]*cfg.MODEL.hin), int(box[0]*cfg.MODEL.hin)),
        #                                 (int(box[3]*cfg.MODEL.hin), int(box[2]*cfg.MODEL.hin)), (255, 0, 0), 7)

        reg_targets, matches = self.produce_target(boxes)

        image = image.astype(np.float32)


        return image, reg_targets,matches

    def produce_target(self,bboxes):
        reg_targets, matches = get_training_targets(bboxes, threshold=cfg.MODEL.MATCHING_THRESHOLD)
        return reg_targets, matches
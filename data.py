import os.path
import numpy as np
import time
import torch
from utils import plot_bev, get_points_in_a_rotated_box, plot_label_map, trasform_label2metric
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms

KITTI_PATH = 'KITTI'

class KITTI(Dataset):

    geometry = {
        'L1': -40.0,
        'L2': 40.0,
        'W1': 0.0,
        'W2': 70.0,
        'H1': -2.5,
        'H2': 1.0,
        'input_shape': (800, 700, 36),
        'label_shape': (200, 175, 7)
    }

    target_mean = np.array([0.008, 0.001, 0.202, 0.2, 0.43, 1.368])
    target_std_dev = np.array([0.866, 0.5, 0.954, 0.668, 0.09, 0.111])

    def __init__(self, frame_range = 10000, use_npy=False, train=True):
        self.frame_range = frame_range
        self.velo = []
        self.use_npy = use_npy

        self.image_sets = self.load_imageset(train)
        self.transform = transforms.Normalize(self.target_mean, self.target_std_dev)

    def __len__(self):
        return len(self.image_sets)

    def __getitem__(self, item):
        scan = self.load_velo_scan(item)
        if not self.use_npy:
            scan = self.lidar_preprocess(scan)
        scan = torch.from_numpy(scan)
        label_map, _ = self.get_label(item)
        self.reg_target_transform(label_map)
        label_map = torch.from_numpy(label_map)
        return scan, label_map

    def reg_target_transform(self, label_map):
        cls_map = label_map[..., 0]
        reg_map = label_map[..., 1:]
        index = np.nonzero(cls_map)
        reg_map[index] = (reg_map[index] - self.target_mean)/self.target_std_dev


    def load_imageset(self, train):
        path = KITTI_PATH
        if train:
            path = os.path.join(path, "train.txt")
        else:
            path = os.path.join(path, "val.txt")

        with open(path, 'r') as f:
            lines = f.readlines() 
            names = []
            for line in lines[:-1]:
                if int(line[:-1]) < self.frame_range:
                    names.append(line[:-1])

            names.append(lines[-1][:6])
            print("There are {} images in txt file".format(len(names)))
            return names

    def get_corners(self, bbox):
        w, h, l, y, z, x, yaw = bbox[8:15]
        y = -y
        yaw = -(yaw + np.pi / 2)
        bev_corners = np.zeros((4, 2), dtype=np.float32)
        bev_corners[0, 0] = x - l/2 * np.cos(yaw) - w/2 * np.sin(yaw)
        bev_corners[0, 1] = y - l/2 * np.sin(yaw) + w/2 * np.cos(yaw)
        bev_corners[1, 0] = x - l/2 * np.cos(yaw) + w/2 * np.sin(yaw)
        bev_corners[1, 1] = y - l/2 * np.sin(yaw) - w/2 * np.cos(yaw)
        bev_corners[2, 0] = x + l/2 * np.cos(yaw) + w/2 * np.sin(yaw)
        bev_corners[2, 1] = y + l/2 * np.sin(yaw) - w/2 * np.cos(yaw)
        bev_corners[3, 0] = x + l/2 * np.cos(yaw) - w/2 * np.sin(yaw)
        bev_corners[3, 1] = y + l/2 * np.sin(yaw) + w/2 * np.cos(yaw)
        reg_target = [np.cos(yaw), np.sin(yaw), x, y, w, l]
        return bev_corners, reg_target


    def get_label(self, index):

        index = self.image_sets[index]
        f_name = (6-len(index)) * '0' + index + '.txt'
        label_path = os.path.join(KITTI_PATH, 'training', 'label_2', f_name)

        object_list = {'Car': 1,'Truck':0, 'DontCare':0, 'Van':0, 'Tram':0}
        label_map = np.zeros(self.geometry['label_shape'], dtype=np.float32)
        label_list = []
        with open(label_path, 'r') as f:
            lines = f.readlines() 
            for line in lines:
                bbox = []
                entry = line.split(' ')
                name = entry[0]
                if name in list(object_list.keys()):
                    bbox.append(object_list[name])
                    bbox.extend([float(e) for e in entry[1:]])
                    if name == 'Car':
                        corners, reg_target = self.get_corners(bbox)
                        self.update_label_map(label_map, corners, reg_target)
                        label_list.append(corners)
        return label_map, label_list


    def load_velo(self):
        velo_files = []
        for file in self.image_sets:
            file = '{}.bin'.format(file)
            velo_files.append(os.path.join(KITTI_PATH, 'training', 'velodyne', file))

        print('Found ' + str(len(velo_files)) + ' Velodyne scans...')
        self.velo = velo_files

        print('done.')

    def point_in_roi(self, point):
        if (point[0] - self.geometry['W1']) < 0.01 or (self.geometry['W2'] - point[0]) < 0.01:
            return False
        if (point[1] - self.geometry['L1']) < 0.01 or (self.geometry['L2'] - point[1]) < 0.01:
            return False
        if (point[2] - self.geometry['H1']) < 0.01 or (self.geometry['H2'] - point[2]) < 0.01:
            return False
        return True

    def lidar_preprocess(self, scan):
        velo = scan
        velo_processed = np.zeros(self.geometry['input_shape'], dtype=np.float32)
        intensity_map_count = np.zeros((velo_processed.shape[0], velo_processed.shape[1]))
        for i in range(velo.shape[0]):
            if self.point_in_roi(velo[i, :]):
                x = int((velo[i, 1]-self.geometry['L1']) / 0.1)
                y = int((velo[i, 0]-self.geometry['W1']) / 0.1)
                z = int((velo[i, 2]-self.geometry['H1']) / 0.1)
                velo_processed[x, y, z] = 1
                velo_processed[x, y, -1] += velo[i, 3]
                intensity_map_count[x, y] += 1
        velo_processed[:, :, -1] = np.divide(velo_processed[:, :, -1],  intensity_map_count, \
                        where=intensity_map_count!=0)
        return velo_processed


def get_data_loader(batch_size, use_npy, frame_range=10000):
    train_dataset = KITTI(frame_range, use_npy=use_npy,train=True)
    train_dataset.load_velo()
    train_data_loader = DataLoader(train_dataset, shuffle=False, batch_size=batch_size)
    
    val_dataset = KITTI(frame_range, use_npy=use_npy, train=False)
    val_dataset.load_velo()
    val_data_loader = DataLoader(val_dataset, batch_size=1)

    return train_data_loader, val_data_loader


def test0():
    k = KITTI()

    id = 2
    k.load_velo()
    tstart = time.time()
    scan = k.load_velo_scan(id)
    processed_v = k.lidar_preprocess(scan)
    label_map, label_list = k.get_label(id)
    print('time taken: %gs' %(time.time()-tstart))
    plot_bev(processed_v, label_list)
    plot_label_map(label_map[:, :, 6])


def find_reg_target_var_and_mean():
    k = KITTI()
    k.load_velo()
    reg_targets = [[] for _ in range(6)]
    for i in range(len(k)):
        label_map, _ = k.get_label(i)
        car_locs = np.where(label_map[:, :, 0] == 1)
        for j in range(1, 7):
            map = label_map[:, :, j]
            reg_targets[j-1].extend(list(map[car_locs]))

    reg_targets = np.array(reg_targets)
    means = reg_targets.mean(axis=1)
    stds = reg_targets.std(axis=1)

    np.set_printoptions(precision=3, suppress=True)
    print("Means", means)
    print("Stds", stds)
    return means, stds

def preprocess_to_npy(train=True):
    k = KITTI(train=train)
    k.load_velo()
    for item, name in enumerate(k.velo):
        scan = k.load_velo_scan(item)
        scan = k.lidar_preprocess(scan)
        path = name[:-4] + '.npy'
        np.save(path, scan)
        print('Saved ', path)
    return

def test():
    train_data_loader, val_data_loader = get_data_loader(2)
    for i, (input, label_map) in enumerate(train_data_loader):
        print("Entry", i)
        print("Input shape:", input.shape)
        print("Label Map shape", label_map.shape)
        if i == 5:
            break

    print("Finish testing train dataloader")


if __name__=="__main__":
    test0()
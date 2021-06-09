import os
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.utils.data.dataloader
import numpy as np
import torchvision
from torch.optim import Adam
from argparse import ArgumentParser
import torch.backends.cudnn as cudnn
import time
from loss import CustomLoss
from data import get_data_loader
from model import LDOPC
from utils import get_model_name, load_config, plot_bev, plot_label_map
from evaluate import non_max_suppression
import sys

parser = ArgumentParser()
parser.add_argument('-bs', '--batch_size', type=int, default=1, help="batch size of the data")
parser.add_argument('-e', '--epochs', type=int, default=100, help='epoch of the train')
parser.add_argument('-lr', '--learning_rate', type=float, default=1e-3, help='learning rate')
args = parser.parse_args()

batch_size = args.batch_size
learning_rate = args.learning_rate
max_epochs = args.epochs

use_cuda = torch.cuda.is_available()

config_name = 'config.json'
config, _, _, _ = load_config(config_name)
train_data_loader, val_data_loader = get_data_loader(batch_size=batch_size, use_npy=config['use_npy'], frame_range=config['frame_range'])


criterion = CustomLoss(device=device, num_classes=1)
optimizer = Adam(net.parameters())


def train(epoch):
    net.train()          
    total_loss = 0.

    for batch_idx, (pc_feature, label_map) in enumerate(train_data_loader):
        N = pc_feature.size(0)
        pc_feature = pc_feature.to(device)
        label_map = label_map.to(device)

        pc_feature = Variable(pc_feature)
        label_map = Variable(label_map)
        predictions = net(pc_feature)
        loss = criterion(predictions, label_map)
        loss /= N
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        total_loss += float(loss.data[0])


        if (batch_idx) % 20 == 0:
            print('train epoch [%d/%d], iter[%d/%d], lr %.7f, aver_loss %.5f' % (epoch,
                                                                                 max_epochs, batch_idx,
                                                                                 len(train_data_loader), learning_rate,
                                                                                 total_loss / (batch_idx + 1)))


        assert total_loss is not np.nan
        assert total_loss is not np.inf

    if not os.path.exists('pretrained_models'):
        os.makedirs('pretrained_models')
    if (epoch) % 2 == 0:
        torch.save(net.state_dict(), 'pretrained_models/model_%d.pth'%epoch)  
    total_loss /= len(train_data_loader)
    print('train epoch [%d/%d] average_loss %.5f' % (epoch, max_epochs, total_loss))


def val(epoch):
    net.eval()
    total_loss = 0.
    for batch_idx, (pc_feature, labels) in enumerate(val_data_loader):
        N = pc_feature.size(0)
        if use_cuda:
            pc_feature = pc_feature.cuda()
            labels = labels.cuda()
        pc_feature = Variable(pc_feature)   
        labels = Variable(labels)  

        out = net(pc_feature)
        loss = criterion(out, labels)
        loss /= N
        total_loss += loss.data[0]

        if (batch_idx + 1) % 10 == 0:
            print('test epoch [%d/%d], iter[%d/%d], aver_loss %.5f' % (epoch,
                                                                       max_epochs, batch_idx, len(val_data_loader),
                                                                       total_loss / (batch_idx + 1)))


    total_loss /= len(val_data_loader)
    print('val epoch [%d/%d] average_loss %.5f' % (epoch, max_epochs, total_loss))

    global best_test_loss 
    best_test_loss = np.inf
    if best_test_loss > total_loss:
        best_test_loss = total_loss
        print('best loss....')


if __name__ == '__main__':
    for epoch in range(max_epochs):
        train(epoch)


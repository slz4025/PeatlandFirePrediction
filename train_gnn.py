from glob import glob
import os
import random
import importlib
import time
import sys
import argparse
import numpy as np
import torch
import simplejson
from tqdm import tqdm 
from torch.autograd import Variable
from dataloader import peat_gnn as peat_loader
import torch.nn.functional as F
from torch_geometric.data import DataLoader, Dataset, Data, NeighborSampler

def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')
        
def accuracy(peat_map, pred, out, actual, in_fire=False):
    pred_val = torch.argmax(pred, dim=1)
    pred_val = pred_val.reshape(-1)
    pred_t = pred_val[peat_map==1].reshape(-1)  
    if in_fire:
        pred = pred_t[out > 0]
    else:
        pred = pred_t[out==0]
    correct = (actual[pred == actual]).reshape(-1).shape[0]
    return correct



def calc_accuracies(pred, out, peat_map):
    #print(peat_map.shape, out.shape)
    in_fire = 0
    correct_in_fire = 0 
    out_fire = 0
    correct_out_fire = 0
    peat_map = peat_map.reshape(-1)
    out = out.reshape(-1)
    out_t = out[peat_map==1]
    pred_t = pred
    reshaped_out = out_t.reshape(-1)
    in_fire_out = reshaped_out[reshaped_out > 0]
    out_fire_out = reshaped_out[reshaped_out == 0]
    in_fire += in_fire_out.shape[0]
    out_fire += out_fire_out.shape[0]
    correct_in_fire += accuracy(peat_map, pred_t, reshaped_out, in_fire_out, True)
    correct_out_fire += accuracy(peat_map, pred_t, reshaped_out, out_fire_out) 
    #print("In_fire : {}/{}, Out_fire : {}/{}".format(correct_in_fire, in_fire, correct_out_fire, out_fire), flush=True)
    #print("Precision", correct_in_fire/(out_fire-correct_out_fire + correct_in_fire+0.001))

    return in_fire, correct_in_fire, out_fire, correct_out_fire

def main(hparams):
    #batch_size = 21
    if hparams.pred_type == 'class':
        loss = torch.nn.CrossEntropyLoss(weight=torch.FloatTensor([hparams.w, 1]).to(device), reduction='sum')
    else:
        loss = torch.nn.MSELoss(reduction='sum')

    model, dataset = get_model(hparams)

    len_dataset = len(dataset)
    
    test_length = int(len_dataset * 0.15)
    val_length = int(len_dataset * 0.15)
    train_length = len_dataset- test_length - val_length
    actual_train_length = (train_length//batch_size ) * batch_size
    actual_test_length = (test_length//batch_size ) * batch_size
    train_val_dataset, test_dataset = torch.utils.data.random_split(dataset, [train_length+val_length, test_length])
    train_dataset, val_dataset = torch.utils.data.random_split(train_val_dataset, [train_length, val_length])

    train_dataloader = DataLoader(
        train_dataset, batch_size=batch_size, num_workers=4, shuffle=True,  drop_last=True)

    val_dataloader = DataLoader(
        val_dataset, batch_size=batch_size, num_workers=4, shuffle=True,  drop_last=True)

    test_dataloader = DataLoader(
        test_dataset, batch_size=batch_size, num_workers=4, shuffle=True,  drop_last=True)
   
    optimizer = torch.optim.Adam(model.parameters(), lr=hparams.lr)
    peat_map = torch.tensor(dataset.peat_map).to(device)
    not_in_peat = peat_map[peat_map==0].reshape(-1).shape[0] * dataset.out_days
    in_peat = peat_map[peat_map==1].reshape(-1).shape[0] * dataset.out_days

    train = []
    
    train_f_acc = []
    train_nf_acc = []
    train_acc = []
    train_p = []

    test = []
    test_f_acc = []
    test_nf_acc = []
    test_acc = []
    test_p = []

    val = []
    val_f_acc = []
    val_nf_acc = []
    val_acc = []
    val_p = []

    model_name = hparams.out + '_' + hparams.pred_type + '_' + hparams.model + '_' + str(hparams.lr) + '_' + str(hparams.dmodel)
    total_idx = 0
    for i in tqdm(range(hparams.epochs)):
        train_length = 0
        train_loss = 0
        total_sum_train = 0
        train_correct = 0
        total_train = 0
        total_train_fire = 0
        total_train_nfire = 0
        train_correct_fire = 0
        train_correct_nfire = 0

        test_length = 0
        test_loss = 0
        total_sum_test = 0
        test_correct = 0
        total_test = 0
        total_test_fire = 0
        total_test_nfire = 0
        test_correct_fire = 0
        test_correct_nfire = 0

        val_length = 0
        val_loss = 0
        total_sum_val = 0
        val_correct = 0
        total_val = 0
        total_val_fire = 0
        total_val_nfire = 0
        val_correct_fire = 0
        val_correct_nfire = 0

        model.train()
        idx = 0
        for data in tqdm(train_dataloader):
            print(idx)
            total_idx += 1
            idx += 1
            optimizer.zero_grad()
            train_length += batch_size
            data.x = data.x.to(device)
            data.edge_index = data.edge_index.to(device)
            data.edge_types = data.edge_types.to(device)
            data.y  = data.y.to(device)
            peat_map = data.peat_map.to(device)
            h = peat_map.size(2)
            w = peat_map.size(-1)            
            pred = model(data)
            pred = pred.reshape(-1, dataset.kh, dataset.kw, model.out_channels).permute(0, 3, 1, 2)
            pred = (pred  * peat_map).float()
            out_val = data.y.reshape(-1, h, w)             
            if hparams.pred_type == 'prediction':
                out_val = out_val.squeeze(2)
                pred = (out_val > 0) * pred * peat_map
                loss_val = loss(pred.squeeze(1), out_val)
                loss_val.backward()
                optimizer.step()
            elif hparams.pred_type=='corr' :
                out_val = out_val.squeeze(2)
                pred = (out_val > 0) * pred * peat_map
                loss_val = loss(pred, out_val)
                loss_val.backward()
                optimizer.step()
            else:
                out_val = out_val
                pred = (pred * peat_map).float()
                loss_val = loss(pred, out_val)
                loss_val.backward()
                optimizer.step()
                in_fire, correct_in_fire, out_fire, correct_out_fire = calc_accuracies(pred, out_val, peat_map.unsqueeze(1)) 
                total_train_fire += in_fire
                total_train_nfire += out_fire
                train_correct_fire += correct_in_fire
                train_correct_nfire += correct_out_fire
            reshape_out = out_val.reshape(-1)
            train_loss += loss_val.item()

        torch.save(model.state_dict(), "/mnt/LARGE/ProjectX/Forecast/models/" + model_name + str(i))

        model.eval()
        idx = 0
        with torch.no_grad():
            idx = 0
            for data in tqdm(val_dataloader):
                idx += 1
                val_length += batch_size
                data.x = data.x.to(device)
                data.edge_index = data.edge_index.to(device)
                data.edge_types = data.edge_types.to(device)
                data.y  = data.y.to(device)
                data.peat_map = data.peat_map.to(device)
                peat_map = data.peat_map
                h = peat_map.size(2)
                w = peat_map.size(-1)            
                pred = model(data)      
                pred = pred.reshape(-1, h, w, model.out_channels).permute(0, 3, 1, 2)
                pred = (pred  * peat_map).float()
                out_val = data.y.reshape(-1, h, w) 
                if hparams.pred_type == 'prediction':
                    out_val = out_val.squeeze(2)
                    pred = (out_val > 0) * pred * peat_map
                    loss_val = loss(pred, out_val)
                elif hparams.pred_type=='corr' :
                    out_val = out_val.squeeze(2)
                    loss_val = loss(pred * peat_map, out_val)
                else:
                    out_val = out_val
                    pred = (pred * peat_map).float()
                    loss_val = loss(pred, out_val)
                    test_loss += loss_val.item()
                    in_fire, correct_in_fire, out_fire, correct_out_fire = calc_accuracies(pred, out_val, peat_map.unsqueeze(1)) 
                    total_val_fire += in_fire
                    total_val_nfire += out_fire
                    val_correct_fire += correct_in_fire
                    val_correct_nfire += correct_out_fire
                val_loss += loss_val.item()   
        print("EPOCH", i, flush=True)
        if total_idx > 700:
            total_idx = 0

        train.append((train_loss)/(train_length+0.01))
        train_p.append(train_correct_fire/(total_train_nfire-train_correct_nfire + train_correct_fire+0.01))
        train_f_acc.append(train_correct_fire/(total_train_fire+0.01))
        train_nf_acc.append(train_correct_nfire/(total_train_nfire+0.01))
        train_acc.append((train_correct_fire+train_correct_nfire)/(total_train_nfire + total_train_fire+0.01))

        val.append((val_loss)/(val_length+0.01))
        val_f_acc.append(val_correct_fire/(total_val_fire+0.01))
        val_nf_acc.append(val_correct_nfire/(total_val_nfire+0.01))
        val_acc.append((val_correct_fire+val_correct_nfire)/(total_val_nfire + total_val_fire+0.01))
        val_p.append(val_correct_fire/(total_val_nfire-val_correct_nfire + val_correct_fire+0.01))
        
        print(train[-1], train_f_acc[-1], train_nf_acc[-1], train_acc[-1], train_p[-1], flush=True)
        print(val[-1], val_f_acc[-1], val_nf_acc[-1], val_acc[-1], val_p[-1], flush=True)

    with open(model_name+'train.txt', 'w') as tl:
        simplejson.dump(train, tl)
    with open(model_name+'test.txt', 'w') as tl:
        simplejson.dump(test, tl)
    
    test_correct = 0  
    total_test = 0
    test_loss = 0
    if hparams.test:
        with torch.no_grad():
            idx = 0
            for data in tqdm(test_dataloader):
                idx += 1
                val_length += batch_size
                data.x = data.x.to(device)
                data.edge_index = data.edge_index.to(device)
                data.edge_types = data.edge_types.to(device)
                data.y  = data.y.to(device)
                data.peat_map = data.peat_map.to(device)
                peat_map = data.peat_map
                h = peat_map.size(2)
                w = peat_map.size(-1)            
                pred = model(data)      
                pred = pred.reshape(-1, h, w, model.out_channels).permute(0, 3, 1, 2)
                pred = (pred  * peat_map).float()
                out_val = data.y.reshape(-1, h, w) 
                if hparams.pred_type == 'prediction':
                    out_val = out_val.squeeze(2)
                    pred = (out_val > 0) * pred * peat_map
                    loss_val = loss(pred, out_val)
                elif hparams.pred_type=='corr' :
                    out_val = out_val.squeeze(2)
                    loss_val = loss(pred * peat_map, out_val)
                else:
                    out_val = out_val
                    pred = (pred * peat_map).float()
                    loss_val = loss(pred, out_val)
                    test_loss += loss_val.item()
                    in_fire, correct_in_fire, out_fire, correct_out_fire = calc_accuracies(pred, out_val, peat_map.unsqueeze(1)) 
                    total_test_fire += in_fire
                    total_test_nfire += out_fire
                    test_correct_fire += correct_in_fire
                    test_correct_nfire += correct_out_fire
                test_loss += loss_val.item()  
        print(total_test_fire, total_test_nfire, test_correct_fire, test_correct_nfire)
        print(test_loss)

def get_arguments():

    parser = argparse.ArgumentParser(description='Training')
    parser.add_argument('--model', type=str, default='gnn')
    parser.add_argument('--CWFIS', type=bool, default=True)
    parser.add_argument('--GSOC', type=bool, default=True)
    parser.add_argument('--MODIS', type=bool, default=False)
    parser.add_argument('--VIIRS', type=bool, default=True)
    parser.add_argument('--ERA5', type=bool, default=True)
    parser.add_argument('--TARNOCAI', type=bool, default=False)
    parser.add_argument('--out', type=str, default='CWFIS')
    parser.add_argument('--in_days', type=int, default=5)
    parser.add_argument('--out_days', type=int, default=1)
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--dmodel', type=int, default=15)
    parser.add_argument('--lr', type=float, default=0.01)
    parser.add_argument('--output_dir', type=str, default="./",
                    help='Where to save stuff')
    parser.add_argument('--snapshot_dir', type=str, default="./",
                    help='model snapshots')
    parser.add_argument('--tb_dir', type=str, default="./",
                    help='tensorboard directory')
    parser.add_argument('--id', type=str, help='unique identifier')
    parser.add_argument('--w', type=float, default=0.001,
                help='weight')
    parser.add_argument("--conf", type=str2bool, nargs='?',
                        const=False, default=True,
                        help="Activate nice mode.")
    parser.add_argument("--parent_id", type=str,
                        help="Activate nice mode.")
    parser.add_argument("--test", type=str2bool, default=False,
                        help="test mode: you can also pass in the file at the top and comment out training ")
    return parser.parse_args()


def get_model(hparams):
    sys.path += ["../", "."]
    Model = importlib.import_module(f"model.{hparams.model}").Model
    all_ft = {'CWFIS', 'GSOC', 'VIIRS', 'TARNOCAI', 'CO2'}
    hparams_dict = vars(hparams) 
    import yaml
    print("CONF", hparams.conf)
    if hparams.conf:
        CONF = yaml.load(open(os.path.join(hparams.output_dir,'conf.yml')), Loader=yaml.FullLoader)
        hparams.dmodel = CONF['dmodel']
        hparams.lr = CONF['lr']
        hparams.model = CONF['model']
        hparams.out = CONF['out']
    
    in_ft = all_ft.intersection(hparams_dict.keys())
    
    dataset = peat_loader.PeatDataset(pred_type=hparams.pred_type, temporal_in=hparams.model == 'unet_gnn_lstm',
                                            in_days=hparams.in_days,
                                            out_days=hparams.out_days, out_ft=hparams.out, 
                                            in_features=in_ft, batch_size=batch_size, 
                                            train=True)
    if hparams.pred_type=='class':
        out_channels = 2
    else:
        out_channels = 1
    model = Model(dataset=dataset.get(0), 
                dmodel=hparams.dmodel, 
                out_channels=out_channels).to(device)
    
    return model, dataset


if __name__ == "__main__":
    batch_size = 1
    hparams = get_arguments()
    hparams.pred_type = 'class' if hparams.out=='CWFIS' else 'prediction'
    if torch.cuda.is_available():
        device = 'cuda:0'
    else:
        device = 'cpu'
    main(hparams)

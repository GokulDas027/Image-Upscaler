# -*- coding: utf-8 -*-
"""ProSR inference.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1ThxLt0jSp62fZcZ2AhfrWCGeeAART3Xu

# Upscaling using pretrained ProSR model

## Downloading Pretrained Checkpoints
"""
# Checkpoints location
# ProSR - https://www.dropbox.com/s/3fjp5dd70wuuixl/proSR.zip?dl=0
# ProSRGAN - https://www.dropbox.com/s/ulkvm4yt5v3vxd8/proSRGAN.zip?dl=0

"""## Imports and Utils"""

# Commented out IPython magic to ensure Python compatibility.
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.multiprocessing as multiprocessing
from torch._C import _set_worker_pids, _set_worker_signal_handlers
from torch.utils.data.dataloader import _BaseDataLoaderIter, DataLoader
from torch.utils.data.dataloader import ExceptionWrapper#, _worker_manager_loop, pin_memory_batch
from torch.utils.data._utils.signal_handling import _set_SIGCHLD_handler
import torchvision.transforms as transforms
import skimage.io as io
from skimage import img_as_float
from skimage.color import rgb2ycbcr
from skimage.metrics import peak_signal_noise_ratio, structural_similarity
import collections
from collections import OrderedDict
from collections.abc import Iterable
from PIL import Image
import sys
import queue
import os
import os.path as osp
import glob
import threading
import random
import matplotlib.pyplot as plt
from math import ceil, floor, log2
# %matplotlib inline

"""## Data preprocessing and loader

### Utils
"""

def pil_loader(path, mode='RGB'):
  # open path as file to avoid ResourceWarning
  # (https://github.com/python-pillow/Pillow/issues/835)
  with open(path, 'rb') as f:
    with Image.open(f) as img:
      return img.convert(mode)

def downscale_by_ratio(img, ratio, method=Image.BICUBIC):
  if ratio == 1:
      return img
  w, h = img.size
  w, h = floor(w / ratio), floor(h / ratio)
  return img.resize((w, h), method)

# Converts a Tensor into a Numpy array
# |imtype|: the desired type of the converted numpy array
def tensor2im(image_tensor, mean=(0.5, 0.5, 0.5), stddev=2.):
  image_numpy = image_tensor[0].cpu().float().numpy()
  image_numpy = (np.transpose(image_numpy,
                              (1, 2, 0)) * stddev + np.array(mean)) * 255.0
  image_numpy = image_numpy.clip(0, 255)
  return np.around(image_numpy).astype(np.uint8)

IMG_EXTENSIONS = ['jpg', 'jpeg', 'png', 'ppm', 'bmp', 'tiff']

def is_image_file(filename):
    return any(
        filename.lower().endswith(extension) for extension in IMG_EXTENSIONS)

def crop_boundaries(im, cs):
    if cs > 1:
        return im[cs:-cs, cs:-cs, ...]
    else:
        return im

def mod_crop(im, scale):
    h, w = im.shape[:2]
    # return im[(h % scale):, (w % scale):, ...]
    return im[:h - (h % scale), :w - (w % scale), ...]

def eval_psnr_and_ssim(im1, im2, scale):
    im1_t = np.atleast_3d(img_as_float(im1))
    im2_t = np.atleast_3d(img_as_float(im2))

    if im1_t.shape[2] == 1 or im2_t.shape[2] == 1:
        im1_t = im1_t[..., 0]
        im2_t = im2_t[..., 0]

    else:
        im1_t = rgb2ycbcr(im1_t)[:, :, 0:1] / 255.0
        im2_t = rgb2ycbcr(im2_t)[:, :, 0:1] / 255.0

    if scale > 1:
        im1_t = mod_crop(im1_t, scale)
        im2_t = mod_crop(im2_t, scale)

        # NOTE conventionally, crop scale+6 pixels (EDSR, VDSR etc)
        im1_t = crop_boundaries(im1_t, int(scale) + 6)
        im2_t = crop_boundaries(im2_t, int(scale) + 6)

    psnr_val = peak_signal_noise_ratio(im1_t, im2_t)
    ssim_val = structural_similarity(
        im1_t,
        im2_t,
        win_size=11,
        gaussian_weights=True,
        multichannel=True,
        data_range=1.0,
        K1=0.01,
        K2=0.03,
        sigma=1.5)

    return psnr_val, ssim_val

def benchmark(scale, upscaled_image=None, target_image=None):
  if upscaled_image==None and target_image==None:
    out = []
    print("\nLet's check the Output and Original folders\n")
    upscaled_image_names = get_filenames("output/", IMG_EXTENSIONS)
    target_image_names = get_filenames("original/", IMG_EXTENSIONS)
    for image in upscaled_image_names:
      image_name = image.split("/")[1]
      print(f"\nComparison of : {image_name}")
      try:
        upscaled_img = pil_loader("output/"+str(image_name))
        target_img = pil_loader("original/"+str(image_name))

        # print(upscaled_img.size)
        # print(target_img.size)

        psnr_val, ssim_val = eval_psnr_and_ssim(upscaled_img, target_img, scale)

        print(f"\nPSNR value : {psnr_val}")
        print(f"SSIM value : {ssim_val}")
        out.append([psnr_val,ssim_val])
      except:
        print("\nNo matching target image found!, make sure the names are same")
    
    return out
    
  elif upscaled_image!=None and target_image!=None:
    upscaled_img = pil_loader(upscaled_image)
    target_img = pil_loader(target_image)

    # print(upscaled_img.size)
    # print(target_img.size)

    psnr_val, ssim_val = eval_psnr_and_ssim(upscaled_img, target_img, scale)

    print(f"Comparison between Upscaled Image : {upscaled_image}")
    print(f"and Original High Res Image       : {target_image}")
    print(f"\nPSNR value : {psnr_val}")
    print(f"SSIM value : {ssim_val}")
    
    return [psnr_val, ssim_val]

  else:    
    print("You can't do that")


def get_filenames(source, image_format):

    # If image_format is a list
    if source is None:
        print('source is none')
        return []
    # Seamlessy load single file, list of files and files from directories.
    source_fns = []
    if isinstance(source, str):
        if os.path.isdir(source) or source[-1] == '*':
            if isinstance(image_format, list):
                for fmt in image_format:
                    source_fns += get_filenames(source, fmt)
            else:
                source_fns = sorted(
                    glob.glob("{}/*.{}".format(source, image_format)))
        elif os.path.isfile(source):
            source_fns = [source]
        assert (all([is_image_file(f) for f in source_fns
                     ])), "Given files contain files with unsupported format"
    elif len(source) and isinstance(source[0], str):
        for s in source:
            source_fns.extend(get_filenames(s, image_format=image_format))
    return source_fns


"""### Dataloader"""

def _worker_loop(dataset, index_queue, data_queue, collate_fn, seed, init_fn, worker_id):
  global _use_shared_memory
  _use_shared_memory = True

  # Intialize C side signal handlers for SIGBUS and SIGSEGV. Python signal
  # module's handlers are executed after Python returns from C low-level
  # handlers, likely when the same fatal signal happened again already.
  # https://docs.python.org/3/library/signal.html Sec. 18.8.1.1
  _set_worker_signal_handlers()

  torch.set_num_threads(1)
  random.seed(seed)
  torch.manual_seed(seed)

  if init_fn is not None:
    init_fn(worker_id)

  while True:
    r = index_queue.get()
    if r is None:
      break
    idx, random_var, batch_indices = r
    try:
      samples = collate_fn([dataset.get(i, random_var) for i in batch_indices])
    except Exception:
      data_queue.put((idx, ExceptionWrapper(sys.exc_info())))
    else:
      data_queue.put((idx, samples))
      del samples

class MyDataLoaderIter(_BaseDataLoaderIter):
  "Iterates once over the DataLoader's dataset, as specified by the sampler"

  def __init__(self, loader):
    self.random_vars = loader.random_vars
    self.dataset = loader.dataset
    self.collate_fn = loader.collate_fn
    self.batch_sampler = loader.batch_sampler
    self.num_workers = loader.num_workers
    self.pin_memory = loader.pin_memory and torch.cuda.is_available()
    self.timeout = loader.timeout
    self.done_event = threading.Event()

    self.sample_iter = iter(self.batch_sampler)

    base_seed = torch.LongTensor(1).random_().item()

    if self.num_workers > 0:
      self.worker_init_fn = loader.worker_init_fn
      self.index_queues = [multiprocessing.Queue() for _ in range(self.num_workers)]
      self.worker_queue_idx = 0
      self.worker_result_queue = multiprocessing.SimpleQueue()
      self.batches_outstanding = 0
      self.worker_pids_set = False
      self.shutdown = False
      self.send_idx = 0
      self.rcvd_idx = 0
      self.reorder_dict = {}

      self.workers = [
          multiprocessing.Process(
              target=_worker_loop,
              args=(self.dataset, self.index_queues[i],
                    self.worker_result_queue, self.collate_fn, base_seed + i,
                    self.worker_init_fn, i))
          for i in range(self.num_workers)]

      if self.pin_memory or self.timeout > 0:
        self.data_queue = queue.Queue()
        if self.pin_memory:
            maybe_device_id = torch.cuda.current_device()
        else:
            # do not initialize cuda context if not necessary
            maybe_device_id = None
        self.worker_manager_thread = threading.Thread(
            target=_worker_manager_loop,
            args=(self.worker_result_queue, self.data_queue, self.done_event, self.pin_memory,
                  maybe_device_id))
        self.worker_manager_thread.daemon = True
        self.worker_manager_thread.start()
      else:
        self.data_queue = self.worker_result_queue

      for w in self.workers:
        w.daemon = True  # ensure that the worker exits on process exit
        w.start()

      _set_worker_pids(id(self), tuple(w.pid for w in self.workers))
      _set_SIGCHLD_handler()
      self.worker_pids_set = True

      # prime the prefetch loop
      for _ in range(2 * self.num_workers):
        self._put_indices()


  def __next__(self):
    if self.num_workers == 0:  # same-process loading
      indices = next(self.sample_iter)  # may raise StopIteration
      random_var = None
      if self.random_vars:
          random_var = random.choice(self.random_vars)
      batch = self.collate_fn([self.dataset.get(i, random_var) for i in indices])
      if self.pin_memory:
          batch = pin_memory_batch(batch)
      return batch

    # check if the next sample has already been generated
    if self.rcvd_idx in self.reorder_dict:
      batch = self.reorder_dict.pop(self.rcvd_idx)
      return self._process_next_batch(batch)

    if self.batches_outstanding == 0:
      self._shutdown_workers()
      raise StopIteration

    while True:
      assert (not self.shutdown and self.batches_outstanding > 0)
      idx, batch = self.data_queue.get()
      self.batches_outstanding -= 1
      if idx != self.rcvd_idx:
        # store out-of-order samples
        self.reorder_dict[idx] = batch
        continue
      return self._process_next_batch(batch)

  def _put_indices(self):
    assert self.batches_outstanding < 2 * self.num_workers
    indices = next(self.sample_iter, None)
    if indices is None:
      return
    chose_var = None
    if self.random_vars:
      chose_var = random.choice(self.random_vars)
    self.index_queues[self.worker_queue_idx].put((self.send_idx, chose_var, indices))
    self.worker_queue_idx = (self.worker_queue_idx + 1) % self.num_workers
    self.batches_outstanding += 1
    self.send_idx += 1

class MyDataLoader(DataLoader):
    """
    Data loader. Combines a dataset and a sampler, and provides
    single- or multi-process iterators over the dataset.

    Arguments:
        dataset (Dataset): dataset from which to load the data.
        batch_size (int, optional): how many samples per batch to load
            (default: 1).
        shuffle (bool, optional): set to ``True`` to have the data reshuffled
            at every epoch (default: False).
        sampler (Sampler, optional): defines the strategy to draw samples from
            the dataset. If specified, the ``shuffle`` argument is ignored.
        num_workers (int, optional): how many subprocesses to use for data
            loading. 0 means that the data will be loaded in the main process
            (default: 0)
        collate_fn (callable, optional)
        pin_memory (bool, optional)
        drop_last (bool, optional): set to ``True`` to drop the last incomplete batch,
            if the dataset size is not divisible by the batch size. If False and
            the size of dataset is not divisible by the batch size, then the last batch
            will be smaller. (default: False)
    """
    __initialized = False

    def __init__(self, dataset, random_vars=[], **kwargs):
        self.random_vars = random_vars
        super().__init__(dataset, **kwargs)

    def __iter__(self):
        return MyDataLoaderIter(self)

    def __len__(self):
        return len(self.batch_sampler)

class Dataset(object):
  """docstring for Dataset"""
  def __init__(self, source, scale, mean,
                stddev, downscale, input_size, **kwargs):
    super(Dataset, self).__init__()
    self.source_fns = source
    self.scale = scale if isinstance(
          scale, Iterable) else [scale]
    self.input_size = [input_size] * len(self.scale) if not isinstance(
          input_size, Iterable) else input_size
    self.mean = mean
    self.stddev = stddev
    self.downscale = downscale
    self.image_loader = pil_loader

    self.source_fns = self.source_fns * len(self.scale)

    # Input normalization
    self.normalize_fn = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(self.mean, self.stddev)
    ])

  def __len__(self):
    return len(self.source_fns)

  def __getitem__(self, index):
    return self.get(index)

  def get(self, index, scale=None):
    if scale:
      assert scale in self.scale, "scale {}".format(scale)
    else:
      scale = self.scale[index % len(self.scale)]

    ret_data = {}
    ret_data['scale'] = scale

    # Load input image
    if len(self.source_fns):
      ret_data['input'] = self.image_loader(self.source_fns[index])
      ret_data['input_fn'] = self.source_fns[index]

      if self.downscale:
        ret_data['input'] = downscale_by_ratio(
            ret_data['input'], scale, method=Image.BICUBIC)
        
    ret_data['bicubic'] = downscale_by_ratio(
          ret_data['input'], 1 / scale, method=Image.BICUBIC)
    
    ret_data['input'] = self.normalize_fn(ret_data['input'])
    ret_data['bicubic'] = self.normalize_fn(ret_data['bicubic'])

    return ret_data

class DataLoader_(MyDataLoader):
  """Hacky way to progressively load scales"""
  def __init__(self, dataset, batch_size=1, scale=None):
    self.dataset = dataset

    super(DataLoader_, self).__init__(
          self.dataset,
          batch_size=batch_size,
          shuffle= False,
          num_workers= 0,#16,
          random_vars= None,
          drop_last=True,
          sampler=None)

def range_splits(tensor,split_ranges,dim):
    """Splits the tensor according to chunks of split_ranges.

    Arguments:
        tensor (Tensor): tensor to split.
        split_ranges (list(tuples(int,int))): sizes of chunks (start,end).
        dim (int): dimension along which to split the tensor.
    """
    return tuple(tensor.narrow(int(dim), start, end - start) for start, end in split_ranges)

def max_dimension_split(tensor,max_dimension,padding,dim):
    """Splits the tensor in chunks of max_dimension

    Arguments:
        tensor (Tensor): tensor to split.
        max_dimension (int): maximum allowed size for dim.
        dim (int): dimension along which to split the tensor.
    """
    assert padding < max_dimension
    dimension = tensor.size(dim)
    num_splits = int(dimension / max_dimension) + \
        int(dimension % max_dimension != 0)
    if num_splits == 1: return [tensor]
    else:
        split_ranges = []
        for i in range(num_splits):
            start = max(0,i * max_dimension-padding)
            end   = min(dimension,(i+1) * max_dimension)
            split_ranges.append((start,end))
    return range_splits(tensor,split_ranges,dim)

def cat_chunks(tensors,padding,dim):
    """Concatenate the tensors along the axis dim.

    Arguments:
        tensors (list(Tensor)): list of tensors to concatenate.
        padding (int): padding used to split the tensors.
        dim (int): dimension along which to cat the tensors.
    """
    def remove_padding(tensor,padding,dim):
        tensor = tensor.narrow(dim,padding,tensor.size(dim)-padding)
        return tensor

    return torch.cat([tensors[0].to('cpu').float()]+
                     [remove_padding(t.to('cpu').float(),padding,dim) for t in tensors[1:]],dim=dim)

def chunks_iter(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]

class DataChunks(object):
    # Assume chunks have the same size
    """Splits a dict of tensor in chunks of max_dimension and concatenate the output tensor.

    Arguments:
        data (dict): dictionary of tensors.
        max_dimension (int): maximum dimension allowed for a tensor.
        padding (int): left padding.
    """

    def __init__(self, data, max_dimension, padding=0, scale=4):
        self.data = data
        self.max_dimension = max_dimension
        self.padding = padding
        self._chunks = []
        self.scale = scale

        self.hlen =  0
        self.vlen = 0


    def iter(self):
        flatten = lambda l: [item for sublist in l for item in sublist]
        keys = self.data.keys()
        chunks_dict = {}
        max_num_chunks = 0
        for key in keys:
            if isinstance(self.data[key],torch.Tensor) and len(self.data[key].shape) > 1:
                chunks = max_dimension_split(self.data[key], self.max_dimension, self.padding, dim=2)
                chunks_of_chunks = [max_dimension_split(c, self.max_dimension, self.padding, dim=3) for c in chunks]

                self.vlen = len(chunks)
                self.hlen = len(chunks_of_chunks[0])

                # flatten the list
                chunks_dict[key] = [item for sublist in chunks_of_chunks for item in sublist]
                max_num_chunks = max(max_num_chunks,len(chunks_dict[key]))

        output = {}
        for key in chunks_dict.keys():
            for i in range(len(chunks_dict[key])):
                if isinstance(self.data[key],torch.Tensor):
                    output[key] = chunks_dict[key][i]
                yield output

    def gather(self,tensor):
        self._chunks.append(tensor)

    def clear(self):
        self._chunks = []


    def _concatenate(self,data):
        horiz_chunks = list(chunks_iter(
            data,int(len(data)/self.vlen)))

        vert_chunks = [cat_chunks(h,self.padding*self.scale,3) for h in horiz_chunks]
        return cat_chunks(vert_chunks,self.padding*self.scale,2) # final tensor

    def concatenate(self):
        if isinstance(self._chunks[0],dict):
            ret_data = {}
            for key in self._chunks[0].keys():
                chunks_key = [d[key] for d in self._chunks]
                ret_data[key] = self._concatenate(chunks_key)
            return ret_data
        else:
            return self._concatenate(self._chunks)

"""## Model Architecture Definition

### Layers
"""

class Conv2d(nn.Module):
    """
    Convolution with alternative padding specified as 'padding_type'
    Conv2d(in_channels, out_channels, kernel_size, stride=1, padding=0,
           padding_type='REFLECTION', dilation=1, groups=1, bias=True)
    if padding is not specified explicitly, compute padding = floor(kernel_size/2)
    """

    def __init__(self, *args, **kwargs):
        super(Conv2d, self).__init__()
        p = 0
        conv_block = []
        kernel_size = args[2]
        dilation = kwargs.pop('dilation', 1)
        padding = kwargs.pop('padding', None)
        if padding is None:
            if isinstance(kernel_size, collections.Iterable):
                assert (len(kernel_size) == 2)
            else:
                kernel_size = [kernel_size] * 2

            padding = (floor((kernel_size[0] - 1) / 2),
                       ceil((kernel_size[0] - 1) / 2),
                       floor((kernel_size[1] - 1) / 2),
                       ceil((kernel_size[1] - 1) / 2))

        try:
            if kwargs['padding_type'] == 'REFLECTION':
                conv_block += [
                    nn.ReflectionPad2d(padding),
                ]
            elif kwargs['padding_type'] == 'ZERO':
                p = padding
            elif kwargs['padding_type'] == 'REPLICATE':
                conv_block += [
                    nn.ReplicationPad2d(padding),
                ]

        except KeyError as e:
            # use default padding 'REFLECT'
            conv_block += [
                nn.ReflectionPad2d(padding),
            ]
        except Exception as e:
            raise e

        conv_block += [
            nn.Conv2d(*args, padding=p, dilation=dilation, **kwargs)
        ]
        self.conv = nn.Sequential(*conv_block)

    def forward(self, x):
        return self.conv(x)

class PixelShuffleUpsampler(nn.Sequential):
    """Upsample block with pixel shuffle"""

    def __init__(self, ratio, planes, woReLU=True):
        super(PixelShuffleUpsampler, self).__init__()
        assert ratio == 3 or log2(ratio) == int(log2(ratio))
        layers = []
        for i in range(int(log2(ratio))):
            if ratio == 3:
                mul = 9
            else:
                mul = 4
            layers += [Conv2d(planes, mul * planes, 3), nn.PixelShuffle(2)]
            if not woReLU:
                layers.append(nn.ReLU(inplace=True))

        self.m = nn.Sequential(*layers)

class ResidualBlock(nn.Module):
    """ResBlock"""

    #  ResBlock def __init__(self, blocks, planes, res_factor=1, act_type='RELU', act_params=dict()):
    def __init__(self,
                 block_type,
                 act_type,
                 planes,
                 res_factor=1,
                 act_params=dict()):
        super(ResidualBlock, self).__init__()
        self.block_type = block_type
        self.act_type = act_type
        self.res_factor = res_factor

        if self.block_type == block_type.BRCBRC:
            self.m = nn.Sequential(
                nn.BatchNorm2d(planes),
                nn.ReLU(inplace=True),
                Conv2d(planes, planes, 3),
                nn.BatchNorm2d(planes),
                nn.ReLU(inplace=True),
                Conv2d(planes, planes, 3),
            )
        elif self.block_type == block_type.CRC:
            self.m = nn.Sequential(
                Conv2d(planes, planes, 3),
                nn.ReLU(inplace=True),
                Conv2d(planes, planes, 3),
            )
        elif self.block_type == block_type.CBRCB:
            self.m = nn.Sequential(
                Conv2d(planes, planes, 3),
                nn.BatchNorm2d(planes),
                nn.ReLU(inplace=True),
                Conv2d(planes, planes, 3),
                nn.BatchNorm2d(planes),
            )

    def forward(self, x):
        return self.res_factor * self.m(x) + x

class _DenseLayer(nn.Sequential):
    def __init__(self, num_input_features, growth_rate, bn_size):
        super(_DenseLayer, self).__init__()
        num_output_features = bn_size * growth_rate

        self.add_module(
            'conv_1',
            nn.Conv2d(
                num_input_features,
                num_output_features,
                kernel_size=1,
                stride=1,
                bias=True)),

        self.add_module('relu_2', nn.ReLU(inplace=True)),
        self.add_module(
            'conv_2',
            Conv2d(num_output_features, growth_rate, 3, stride=1, bias=True)),

    def forward(self, x):
        new_features = super(_DenseLayer, self).forward(x)
        return torch.cat([x, new_features], 1)

class _DenseBlock(nn.Sequential):
    def __init__(self, num_layers, num_input_features, bn_size, growth_rate):
        super(_DenseBlock, self).__init__()
        for i in range(num_layers):
            layer = _DenseLayer(num_input_features + i * growth_rate,
                                growth_rate, bn_size)
            self.add_module('denselayer%d' % (i + 1), layer)

class DenseResidualBlock(nn.Sequential):
    def __init__(self, **kwargs):
        super(DenseResidualBlock, self).__init__()
        self.res_factor = kwargs.pop('res_factor')

        self.dense_block = _DenseBlock(**kwargs)
        num_features = kwargs['num_input_features'] + kwargs['num_layers'] * kwargs['growth_rate']

        self.comp = CompressionBlock(
            in_planes=num_features,
            out_planes=kwargs['num_input_features'],
        )

    def forward(self, x, identity_x=None):
        if identity_x is None:
            identity_x = x
        return self.res_factor * super(DenseResidualBlock,
                                       self).forward(x) + identity_x

class CompressionBlock(nn.Sequential):
    def __init__(self, in_planes, out_planes, dropRate=0.0):
        super(CompressionBlock, self).__init__()
        self.conv1 = nn.Conv2d(
            in_planes,
            out_planes,
            kernel_size=1,
            stride=1,
            padding=0,
            bias=False)
        self.droprate = dropRate

    def forward(self, x):
        out = super(CompressionBlock, self).forward(x)
        if self.droprate > 0:
            out = F.dropout(
                out, p=self.droprate, inplace=False, training=self.training)
        return out

"""### Architecture"""

class ProSR(nn.Module):
    """docstring for PyramidDenseNet"""

    def __init__(self, residual_denseblock, num_init_features, bn_size,
                 growth_rate, ps_woReLU, level_config, level_compression,
                 res_factor, max_num_feature, max_scale, **kwargs):
        super(ProSR, self).__init__()
        self.max_scale = max_scale
        self.n_pyramids = int(log2(self.max_scale))

        # used in curriculum learning, initially set to the last scale
        self.current_scale_idx = self.n_pyramids - 1

        self.residual_denseblock = residual_denseblock
        self.DenseBlock = _DenseBlock
        self.Upsampler = PixelShuffleUpsampler
        self.upsample_args = {'woReLU': ps_woReLU}

        denseblock_params = {
            'num_layers': None,
            'num_input_features': num_init_features,
            'bn_size': bn_size,
            'growth_rate': growth_rate,
        }

        num_features = denseblock_params['num_input_features']

        # Initiate network

        # each scale has its own init_conv
        for s in range(1, self.n_pyramids + 1):
            self.add_module('init_conv_%d' % s, Conv2d(3, num_init_features,
                                                       3))

        # Each denseblock forms a pyramid
        for i in range(self.n_pyramids):
            block_config = level_config[i]
            pyramid_residual = OrderedDict()

            # starting from the second pyramid, compress the input features
            if i != 0:
                out_planes = num_init_features if level_compression <= 0 else int(
                    level_compression * num_features)
                pyramid_residual['compression_%d' % i] = CompressionBlock(
                    in_planes=num_features, out_planes=out_planes)
                num_features = out_planes

            # serial connect blocks
            for b, num_layers in enumerate(block_config):
                denseblock_params['num_layers'] = num_layers
                denseblock_params['num_input_features'] = num_features
                # residual dense block used in ProSRL and ProSRGAN
                if self.residual_denseblock:
                    pyramid_residual['residual_denseblock_%d' %
                                     (b + 1)] = DenseResidualBlock(
                                         res_factor=res_factor,
                                         **denseblock_params)
                else:
                    block, num_features = self.create_denseblock(
                        denseblock_params,
                        with_compression=(b != len(block_config) - 1),
                        compression_rate=kwargs['block_compression'])
                    pyramid_residual['denseblock_%d' % (b + 1)] = block

            # conv before upsampling
            block, num_features = self.create_finalconv(
                num_features, max_num_feature)
            pyramid_residual['final_conv'] = block
            self.add_module('pyramid_residual_%d' % (i + 1),
                            nn.Sequential(pyramid_residual))

            # upsample the residual by 2 before reconstruction and next level
            self.add_module(
                'pyramid_residual_%d_residual_upsampler' % (i + 1),
                self.Upsampler(2, num_features, **self.upsample_args))

            # reconstruction convolutions
            reconst_branch = OrderedDict()
            out_channels = num_features
            reconst_branch['final_conv'] = Conv2d(out_channels, 3, 3)
            self.add_module('reconst_%d' % (i + 1),
                            nn.Sequential(reconst_branch))

        # init_weights(self)

    def get_init_conv(self, idx):
        """choose which init_conv based on curr_scale_idx (1-based)"""
        return getattr(self, 'init_conv_%d' % idx)

    def forward(self, x, upscale_factor=None, blend=1.0):
        if upscale_factor is None:
            upscale_factor = self.max_scale
        else:
            valid_upscale_factors = [
                2**(i + 1) for i in range(self.n_pyramids)
            ]
            if upscale_factor not in valid_upscale_factors:
                print("Invalid upscaling factor {}: choose one of: {}".format(
                    upscale_factor, valid_upscale_factors))
                raise SystemExit(1)

        feats = self.get_init_conv(log2(upscale_factor))(x)
        for s in range(1, int(log2(upscale_factor)) + 1):
            if self.residual_denseblock:
                feats = getattr(self, 'pyramid_residual_%d' % s)(feats) + feats
            else:
                feats = getattr(self, 'pyramid_residual_%d' % s)(feats)
            feats = getattr(
                self, 'pyramid_residual_%d_residual_upsampler' % s)(feats)

            # reconst residual image if reached desired scale /
            # use intermediate as base_img / use blend and s is one step lower than desired scale
            if 2**s == upscale_factor or (blend != 1.0 and 2**
                                          (s + 1) == upscale_factor):
                tmp = getattr(self, 'reconst_%d' % s)(feats)
                # if using blend, upsample the second last feature via bilinear upsampling
                if (blend != 1.0 and s == self.current_scale_idx):
                    base_img = nn.functional.upsample(
                        tmp,
                        scale_factor=2,
                        mode='bilinear',
                        align_corners=True)
                if 2**s == upscale_factor:
                    if (blend != 1.0) and s == self.current_scale_idx + 1:
                        tmp = tmp * blend + (1 - blend) * base_img
                    output = tmp

        return output

    def create_denseblock(self,
                          denseblock_params,
                          with_compression=True,
                          compression_rate=0.5):
        block = OrderedDict()
        block['dense'] = self.DenseBlock(**denseblock_params)
        num_features = denseblock_params['num_input_features']
        num_features += denseblock_params['num_layers'] * denseblock_params['growth_rate']

        if with_compression:
            out_planes = num_features if compression_rate <= 0 else int(
                compression_rate * num_features)
            block['comp'] = CompressionBlock(
                in_planes=num_features, out_planes=out_planes)
            num_features = out_planes

        return nn.Sequential(block), num_features

    def create_finalconv(self, in_channels, max_channels=None):
        block = OrderedDict()
        if in_channels > max_channels:
            block['final_comp'] = CompressionBlock(in_channels, max_channels)
            block['final_conv'] = Conv2d(max_channels, max_channels, (3, 3))
            out_channels = max_channels
        else:
            block['final_conv'] = Conv2d(in_channels, in_channels, (3, 3))
            out_channels = in_channels
        return nn.Sequential(block), out_channels

    def class_name(self):
        return 'ProSR'


"""## Inferencing on model"""

def upscale(model, data_loader, mean, stddev, scale, gpu, max_dimension=0, padding=0):
  upscaled_img = []
  with torch.no_grad():
    psnr_mean = 0
    ssim_mean = 0

    for iid, data in enumerate(data_loader):
      if max_dimension:
        print(len(data['input']))
        data_chunks = DataChunks({'input':data['input']},
                                  max_dimension,
                                  padding, scale)
        for chunk in data_chunks.iter():
          input = chunk['input']
          if gpu:
            input = input.cuda()
          output = model(input,scale)
                    
          data_chunks.gather(output)
          output = data_chunks.concatenate() + data['bicubic']
      else:
        input = data['input']
        if gpu:
          input = input.cuda()
        output = model(input, scale).cpu() + data['bicubic']
      sr_img = tensor2im(output, mean, stddev)
      ip_img = tensor2im(data['bicubic'], mean, stddev)
      print(len(sr_img))
      psnr_val, ssim_val = eval_psnr_and_ssim(
                    sr_img, ip_img, scale)
      psnr_mean += psnr_val
      ssim_mean += ssim_val
      # io.imshow(sr_img)
      fn = osp.join('output', osp.basename(data['input_fn'][0]))
      io.imsave(fn, sr_img)
      
      upscaled_img.append(sr_img)
    
    # calculating the mean psnr annd ssim values of upscale
    try:
        iid += 1
    except:
        iid = 1
    psnr_mean /= iid
    ssim_mean /= iid

    print(f"PSNR value : {psnr_mean}")
    print(f"SSIM value : {ssim_mean}")
    
  return upscaled_img

"""## Input Procesing and loading"""

def main(scale, gan=True, keep_res=True):
  # ensure the scale value to be 2,4 or 8
  if scale <= 2:
    scale = 2
  elif scale >= 8:
    scale = 8
  else:
    scale = 4

  # checking gpu availability
  gpu = torch.cuda.is_available()
  print("GPU availability : " + str(gpu))

  # input images from the folder
  input_path = 'input' # image input path
  if not osp.isdir('input'):
    print('file no found')
    os.makedirs('input')
  IMG_EXTENSIONS = ['jpg', 'jpeg', 'png', 'ppm', 'bmp', 'tiff']
  input_images = get_filenames(input_path, IMG_EXTENSIONS)
  
  # chosing the model for upsacling
  if gan:
    if scale==8:
      filepath = 'checkpointsGAN/proSRGAN_x8.pth'
    else:
      filepath = 'checkpointsGAN/proSRGAN_x4.pth'
  else:
    if scale==8:
      filepath = 'checkpoints/proSR_x8.pth'
    elif scale==4:
      filepath = 'checkpoints/proSR_x4.pth'
    else:
      filepath = 'checkpoints/proSR.pth'

  # load the model checkpoint for gpu or cpu
  if gpu:
    checkpoint = torch.load(filepath)
  else:
    device = torch.device('cpu')
    checkpoint = torch.load(filepath, map_location=device)

  # loading the model weights
  model = ProSR(**checkpoint['params']['G'])
  model.load_state_dict(checkpoint['state_dict'])

  # model to test mode
  model.eval()

  # move model to gpu if gpu available
  if gpu:
    model = model.cuda()

  # scale = checkpoint['params']['data']['scale'][2]
  input_size = checkpoint['params']['data']['input_size']
  mean = checkpoint['params']['train']['dataset']['mean']
  stddev = checkpoint['params']['train']['dataset']['stddev']
  downscale = keep_res #checkpoint['params']['test']['dataset']['downscale']

  # printing the config values
  print(f'scale        : {scale}')
  print(f'input_size   : {input_size}')
  print(f'mean         : {mean}')
  print(f'stddev       : {stddev}')
  print(f'downscale    : {downscale}')

  # process the dataset to input
  dataset = Dataset(
        input_images,
        scale,
        mean,
        stddev,
        downscale,
        input_size=None)
        # source, scale, mean, stddev, downscale, input_size
  data_loader = DataLoader_(dataset, batch_size=1)

  # create the output folder if it doesn't exist already
  if not osp.isdir('output'):
    os.makedirs('output')

  # upscaling the image
  upscaled_images = upscale(model, data_loader, mean, stddev, scale, gpu)

  return upscaled_images

# upscaled_images = main(8)

'''Displaying the upscaled image'''
# for img in upscaled_images:
#   io.imshow(img)

if __name__ == "__main__":
    scale = 2
    upscaled_images = main(scale, gan=True, keep_res=False)
    comparison_list = benchmark(scale)


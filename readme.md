** Educational Purposes ** 

## Instructions to SetUp

### Anaconda

#### Create and activate conda environment
```
conda create --name pytorch

conda activate pytorch
```

#### Install requirements
```
conda install pytorch==1.5.0 torchvision -c pytorch
conda install scikit-image cython
conda install -c anaconda flask==1.1.2
pip install easydict
```
### Based on the [paper](https://igl.ethz.ch/projects/prosr/prosr-cvprw-2018-wang-et-al.pdf)

> **A Fully Progressive Approach to Single-Image Super-Resolution**
> by **Wang-Yifan et al** at **CVPRW 2018**

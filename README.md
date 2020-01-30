# python_vmware_wrapper
Wrapper for VMWare's pyvmomi API. Presents a friendly interface to let you interact with vmware without worrying (much) about the API

## Overview

Pyvmomi is VMWare's python wrapper for their vSphere API. It's a SOAP based system with managed objects passed back for
you to interact with in your own code. Unfortunately it has several quirks and requires a thorough knowledge of the API
to be usable for most developers. 

I've also found, through experience writing code which interacts with it to manage large VMWare estates (>10k VMs 
globally), that it has a few annoying habits/bugs in it. 

This library is an attempt to provide a nice wrapper for other developers to use which abstracts away the complexities 
of VMWare's API, and at the same time, handles some of the quirks and bugs so that you don't have to.  

## Usage

VSphere is the core class of this library. It needs to be instantiated with enough information to connect to VSphere, 
after that, you just tell it by name what you want to interact with, and it will find the object in VMWare and cache it 
in a class variable. Subsequent operations on that object will then use the held copy of it (unless a refresh is 
requested). 

Note that name lookups are slow, especially if you have a few thousand VMs kicking about and you're trying to find one 
of them :) It is advisable to pre-cache them using the uuid lookup. They will then be available by name for subsequent 
commands. This isn't as nice as I'd like it, but it's a necessary performance workaround.

Note that while the VSphere class abstracts away the operations of pyvmomi, it still presents the objects it's working with in case 
you want to directly interact with them.

## Supports

VMWare vSphere 6.5

## Design

The idea is for the rest of the system it lives in to use the VSphere class and not have to worry at all about the
underlying API or pyvmomi. The rest of the system should just deal with names of things and the occasional UUID. 
However, VSphere does hand the managed object over when you look it up, and of course you can fish the object out of the cached
object list. 

To keep the VSphere class manageable in terms of line count and complexity, it farms out the operations to the various 
functions in support_functions. It injects itself into those functions so that cached objects, all other operations 
as well as the logger are available to that function. 

## Origin

The original version of this was written for https://github.com/drcsh/vmware-deploy it has since moonlighted in 
production systems, and come out the other side here.

## Acknowledgements

Much of the code for interacting with VMWare is borrowed and modified from snippets in the pyvmomi community samples: 
https://github.com/vmware/pyvmomi-community-samples

Additionally, this is based on some work undertaken by myself and a former colleague: https://github.com/inuwashi

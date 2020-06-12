from pyVmomi import vim
from pyVim.connect import SmartConnect, Disconnect


import logging
import argparse
import atexit
import getpass
import ssl
import yaml

def RestartVm(vm_name,vmware_host):
   context = None
   #server = 'vcenter01.utum.de', username = , password = , session = session)
   if hasattr(ssl, '_create_unverified_context'):
      context = ssl._create_unverified_context()
   si = SmartConnect(host=vmware_host["host"],
                     user=vmware_host["user"],
                     pwd=vmware_host["password"],
                     port=vmware_host.get("port",443),
                     sslContext=context)
   if not si:
       logging.error("Could not connect to the specified host using specified username and password")
       return -1


   atexit.register(Disconnect, si)

   vm_dict = {}
   content = si.RetrieveContent()
   for child in content.rootFolder.childEntity:
      if hasattr(child, 'vmFolder'):
         datacenter = child
         vmFolder = datacenter.vmFolder
         vmList = vmFolder.childEntity
         for vm in vmList:
            vm_dict.update(getAllVms(vm))
   vm = vm_dict.get(vm_name)
   if not vm is None:
      status = vm.guest.toolsStatus
      if status == "toolsOk":
         logging.info("soft reloaded vm")
         vm.RebootGuest()
      else:
         logging.info("hard reset vm")
         vm.ResetVM_Task()
      return 0
   return -1


def getAllVms(vm,depth=1,maxdepth=10):
   if depth > maxdepth:
      return []
   vm_dict = {}
   # if this is a group it will have children. if it does, recurse into them
   # and then return
   if hasattr(vm, 'childEntity'):
      vmList = vm.childEntity
      for c in vmList:
         vm_dict.update(getAllVms(c, depth+1))
      return vm_dict
   # if this is a vApp, it likely contains child VMs
   # (vApps can nest vApps, but it is hardly a common usecase, so ignore that)
   if isinstance(vm, vim.VirtualApp):
      vmList = vm.vm
      for c in vmList:
         vm_dict.update(getAllVms(c, depth+1))
      return vm_dict
   vm_dict[vm.name] = vm
   return vm_dict

def execute(**kwargs):
   vm_name =  kwargs.get("vm_name")
   vcenter_name = kwargs.get("instance")
   config_path = kwargs.get("configfile","vmware.yml")
   if vm_name is None or vcenter_name is None or config_path is None:
      logging.error("missing vm_name, vcenter instance or config file path")
      return -1
   config = None
   with open(config_path, 'r') as stream:
      try:
         config = yaml.safe_load(stream)
      except yaml.YAMLError as exc:
         logging.error("failed to load config")
         logging.error(exc)
         return -1
   if config is None:
      logging.error("failed to load config")
      return -1

   vmware_instance = None
   if vcenter_name in config["hosts"]:
      vmware_instance = config["hosts"][vcenter_name]
   else:
      vmware_instance = config["hosts"]["default"]
   if not "host" in vmware_instance:
      vmware_instance["host"] = vcenter_name
   if kwargs.get("function","") == "restart-vm":
      return RestartVm(vm_name,vmware_instance)
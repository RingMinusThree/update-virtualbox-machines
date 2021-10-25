#!/usr/bin/env python3

import subprocess
import time
import sys


flag = "UpdateVirtualBoxMachinesFinalSignalOperationIsComplete"
newline = "\r\n"
verbose = False


def parse_arguments(argv):
    """Parse given command line arguments"""

    if 3 > len(argv):
        return False

    argv.reverse()

    argv.pop() # Remove script name
    arguments = {
        "username": argv.pop(),
        "password": argv.pop(),
        "remove": False,
        "shutdown": False,
        "verbose": False
    }

    while len(argv):
        arg = argv.pop()

        if "-h" == arg:
            return False
        elif "-r" == arg:
            arguments["remove"] = True
        elif "-s" == arg:
            arguments["shutdown"] = True
        elif "-v" == arg:
            arguments["verbose"] = True
            global verbose
            verbose = True
        else:
            print("Unknown argument:", arg, newline)
            return False

    return arguments

def print_help():
    """Print help instructions"""

    print("""Usage:
python3 update.py $username $password [arguments]

Arguments
-h  help        Display help
-r  remove      Autoremove packages
-s  shutdown    Shutdown host once finished
-v  verbose     Print detailed information""")
    exit()

def find_property_value(vminfo, property):
    """Retrieve value from VBoxManage showvminfo"""

    for line in vminfo.split(newline):
        if line.startswith(property):
            return line[line.index("\"") + 1:-1]

    raise Exception("find_property_value() - Property '{0}' not found".format(property))

def get_host_os():
    """Check the host OS type"""

    if "win32" == sys.platform:
        return "Windows"
    return "Linux"

def vboxmanage(command):
    """Run VBoxManage command"""

    binary = ""

    if "Windows" == get_host_os():
        binary = '"C:/Program Files/Oracle/VirtualBox/VBoxManage.exe"'
    else:
        binary = "VBoxManage"

    p = subprocess.Popen(binary + " " + command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    stdout, stderr = p.communicate()
    stdout = stdout.decode("utf-8")
    stderr = stderr.decode("utf-8")
    return stdout + stderr

def parse_machines(list):
    """Parse response from 'VBoxManage list vms'"""

    vms = []
    for line in list.split(newline):

        # validate line format
        if "" == line:
            return vms
        elif not (
            2 == line.count("\"") and
            4 == line.count("-") and
            1 == line.count("{") and
            1 == line.count("}")
        ):
            raise Exception("Command 'list vms' returned unknown format")

        vm = {}
        line = line[1:] # remove first quote
        vm["name"] = line[:line.index("\"")]
        vm["uuid"] = line[line.index("\"") + 3:-1] # skip quote, space & braces
        vms.append(vm)

def print_if_verbose(message):
    """Message to print if verbose option set"""

    if verbose:
        print(message)

def run_update_command(vm, args):
    """Run update command on the guest OS"""

    managers = discover_package_managers(vm, args)
    command = get_update_command(managers, args)

    return run_command(vm, args, command)

def discover_package_managers(vm, args):
    """Identify which package managers to guest is using"""

    managers = {
        "apt": False,
        "snap": False,
    }

    for manager in managers:
        response = run_command(vm, args, "which {0}".format(manager))

        if response:
            managers[manager] = True

    return managers

def get_update_command(managers, args):
    """Construct update command based on options"""

    command = ""

    if managers["apt"]:
        command += "{0} apt update && {0} apt upgrade -y && "
        if args["remove"]:
            command += "{0} apt autoremove -y && "

    if managers["snap"]:
        command += "{0} snap refresh && "

    command += "echo {0}".format(flag)

    return command.format("echo {0} | sudo -S".format(args["password"]))

def run_command(vm, args, command):
    """Run given command on the guest"""

    vbox_command = ('guestcontrol {0} --username {1} --password {2}'
        'run --exe "/bin/sh" -- "/bin/sh" "-c" "{3}"'
        '').format(vm["uuid"], args["username"], args["password"], command)

    return vboxmanage(vbox_command)

def update(vm, args):
    """Update virtual machine"""

    vm_info = vboxmanage("showvminfo {0} --machinereadable".format(vm["uuid"]))

    # Skip VMs in saved or running state
    if "poweroff" != find_property_value(vm_info, "VMState"):
        return False

    if "Windows" == find_property_value(vm_info, "ostype"):
        return False

    print_if_verbose("Starting machine")

    response = vboxmanage("startvm {0}".format(vm["uuid"]))
    time.sleep(60) # Wait for VM to start

    # Check that machine started
    if "successfully started" not in response:
        return False

    print_if_verbose("Machine started successfully")

    attempt_count = 0
    error_detected = False
    print_if_verbose("Waiting to run update command")

    # Loop until VM is running and command succeeds
    while not error_detected:
        attempt_count += 1
        if 5 < attempt_count:
            error_detected = True
            break

        response = run_update_command(vm, args)

        if "error:" in response:
            time.sleep(30)
        else:
            break

    attempt_count = 0
    print_if_verbose("Update command {0}".format("failed" if error_detected else "run"))
    print_if_verbose("Waiting for update to finish")

    # Loop until update is complete
    while not error_detected:
        attempt_count += 1
        if 20 < attempt_count: # 10 minutes (20 * 30 seconds)
            error_detected = True
            break

        if flag in response:
            break
        else:
            time.sleep(30)

    print_if_verbose("Update {0}".format("timed out" if error_detected else "completed"))
    print_if_verbose("Shutting down machine")

    vboxmanage("controlvm {0} acpipowerbutton".format(vm["uuid"]))

    # Wait for machine to shutdown
    time.sleep(30)
    while True:
        vm_info = vboxmanage("showvminfo {0} --machinereadable".format(vm["uuid"]))
        if "poweroff" == find_property_value(vm_info, "VMState"):
            break;
        time.sleep(15)

    print_if_verbose("Shutdown complete")

    return True

def main():
    args = parse_arguments(sys.argv)
    if not args:
        print_help()
        return False

    machines = parse_machines(vboxmanage("list vms"))

    print(len(machines), "found")
    for i in range(len(machines)):
        print()
        print("Updating", i, machines[i]["name"])
        success = update(machines[i], args)

        print_if_verbose("Update successful" if success else "Update failed")

    if args["shutdown"]:
        if "Windows" == get_host_os():
            subprocess.Popen("shutdown /s /t 60")
        else:
            subprocess.Popen("shutdown")

main()

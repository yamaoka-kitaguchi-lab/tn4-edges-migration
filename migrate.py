"""
Migrate VLAN configurations from Tn3 to Tn4
"""

from getpass import getpass
from lxml import etree
import csv
import sys

from jinja2 import Template, Environment
from jnpr.junos import Device
from jnpr.junos.utils.config import Config
from jnpr.junos.exception import ConnectError
from jnpr.junos.exception import LockError
from jnpr.junos.exception import UnlockError
from jnpr.junos.exception import ConfigLoadError
from jnpr.junos.exception import CommitError


def backup(dev, savedir="."):
    hostname = dev.facts["hostname"]
    with open(savedir+"/"+hostname+"_config.xml", "w") as fd:
        r = dev.rpc.get_config(options={"format": "set"})
        d = etree.tostring(r, encoding='unicode', pretty_print=True)
        fd.write(d)
    with open(savedir+"/"+hostname+"_config.txt", "w") as fd:
        r = dev.rpc.get_config(options={"format": "text"})
        fd.write(r.text)


def migrate(tn3_swip, tn4_swip, tn3_user, tn3_pass, tn4_user, tn4_pass, dry=False):
    try:
        tn3_sw = Device(host=tn3_swip, user=tn3_user, password=tn3_pass)
        tn3_sw.open()
        tn4_sw = Device(host=tn4_swip, user=tn4_user, password=tn4_pass)
        tn4_sw.open()
    except ConnectionError as err:
        print("E: Failed to connect to {}. Abort migration.".format(err))
        return

    cf = tn3_sw.rpc.get_config()
    vlans = cf.find("vlans")
    interfaces = cf.find("interfaces")

    for vlan in vlans:
        for el in vlan:
            if el.tag in ["name", "vlan-id", "description"]:
                continue
            vlan.remove(el)
            print("W: Ignored VLAN configuration ({}={})".format(el.tag, el.text))
    for interface in interfaces:
        ifname = interface.find("name")
        iftype = ifname.text.split("-")[0]
        if iftype != "ge":
            interfaces.remove(interface)
            continue
        ifnumber = int(ifname.text.split("/")[2])
        if ifnumber >= 24:
            ifname.text = "mge-0/0/" + ifnumber
        for el in interface.xpath("//port-mode"):
            el.tag = "interface-mode"

    dry or backup(tn3_sw, savedir="./config/tn3")
    dry or backup(tn4_sw, savedir="./config/tn4/previous")
    with Config(tn4_sw, mode="exclusive") as cu:
        cu.rollback(0)
        cu.load(template_path="./common.j2", format="text", merge=True)
        cu.load(vlans, merge=True)
        cu.load(interfaces, merge=True)
        dry and cu.pdiff() is None or cu.commit()
    dry or backup(tn4_sw, savedir="./config/tn4/current")


def main(inventory_csv, dry=False):
    tn3_user = input("Tn3 Username: ")
    tn3_pass = getpass("Tn3 Password: ")
    tn4_user = input("Tn4 Username: ")
    tn4_pass = getpass("Tn4 Password: ")

    inventory = []
    with open(inventory_csv, newline="") as fd:
        inventory = [r for r in csv.reader(fd)][1:]

    total = len(inventory)
    for i, pair in enumerate(inventory):
        tn3_swip, tn4_swip = pair
        print("I: Migrating {} ({}/{})".format(tn3_swip, i+1, total))
        migrate(tn3_swip, tn4_swip, tn3_user, tn3_pass, tn4_user, tn4_pass, dry=dry)


if __name__ == "__main__":
    inventory = sys.argv[1]
    main(inventory, dry=True)


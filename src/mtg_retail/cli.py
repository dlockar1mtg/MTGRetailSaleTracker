import argparse
import json
from .core import init_db, import_stores, validate, export

def main():
    p=argparse.ArgumentParser(description='MTG retailer registry')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init-db')
    imp=sub.add_parser('import-stores');imp.add_argument('csv')
    sub.add_parser('validate')
    exp=sub.add_parser('export');exp.add_argument('--out',default='output')
    args=p.parse_args()
    if args.command=='init-db': init_db();print('Database initialized')
    elif args.command=='import-stores': print(f'Imported {import_stores(args.csv)} in-radius candidate rows')
    elif args.command=='validate': print(json.dumps(validate(),indent=2))
    elif args.command=='export': export(args.out);print('Governed exports written')
if __name__=='__main__': main()

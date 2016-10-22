#! /usr/bin/env python3
import argparse
import configparser
import importlib
import logging
import os
import re
import sys
import time

from peewee import CharField, IntegrityError, Model, PostgresqlDatabase, ProgrammingError
from playhouse.migrate import PostgresqlMigrator, migrate


_db = PostgresqlDatabase(None)
_schema = 'public'


class JambiModel(Model):
    ref = CharField(primary_key=True)

    class Meta:
        db_table = 'jambi'
        database = _db
        schema = _schema


class Jambi(object):
    """A database migration helper for peewee."""
    def __init__(self):
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger('peewee').setLevel(logging.INFO)
        self.logger = logging.getLogger('jambi')
        self.db, self.db_schema = self.__get_db_and_schema_from_config()

    def upgrade(self, ref):
        """migrate the database to the supplied version"""
        current_ref = self.inspect()
        if current_ref is None:
            self.logger.error('upgrade halted: you must initialize jambi first')
            return
        migrations = self.find_migrations()
        migrations = tuple(filter(lambda x: x[1] > current_ref, migrations))
        if any(migrations):
            self.logger.info('migrating to "{}"'.format(ref))
            self.db.connect()
            with self.db.atomic():
                for n, v, m in migrations:
                    self.logger.info('upgrading to version {}'.format(v))
                    migrator = PostgresqlMigrator(self.db)
                    upgrades = m.upgrade(migrator)
                    migrate(*upgrades)
                print(migrations[-1][1])
                self.__set_version(migrations[-1][1])
            self.db.close()
            self.logger.info(self.inspect())
        else:
            self.logger.info('you are already up to date')
        return

    def downgrade(self, ref):
        """downgrade the db to the supplied version"""
        return NotImplemented

    def latest(self):
        """returns the latest version in the migrations folder"""
        return NotImplemented

    def find_migrations(self):
        """find, import, and return all migration files as modules"""
        fileloc = self.getconfig('migrate', 'location')
        fullpath = os.path.join(os.getcwd(), fileloc)
        try:
            filenames = os.listdir(fullpath)
        except FileNotFoundError:
            self.logger.error('unable to find migration folder "{}"'.format(fullpath))
            return
        filenames = filter(lambda x: x.startswith('version_') and x.endswith('.py'), filenames)
        filepaths = [(os.path.join(fullpath, f), f.replace('.py', '')) for f in filenames]
        migrations = []
        for fp, mn in filepaths:
            module_name = '.'.join([fileloc.replace('/','.').strip('.'), mn])
            try:
                ver = int(re.search(r'version_(\d+)', mn).group(1))
            except:
                self.logger.warning('cannot parse version number from \'{}\', '
                                    'skipping'.format(mn))
                continue
            self.logger.debug('found {} at version {}'.format(module_name, ver))
            migrations.append((module_name, ver, importlib.import_module(module_name)))
        return sorted(migrations, key=lambda x: x[1])

    def getconfig(self, section, key):
        config = configparser.ConfigParser()
        config.read('jambi.conf')
        return config[section][key]

    def inspect(self):
        """inspect the database and report its version"""
        self.db.connect()
        result = None
        try:
            jambi_versions = JambiModel.select().limit(1)
            if any(jambi_versions):
                field = jambi_versions[0].ref
                try:
                    result = int(field)
                except ValueError:
                    self.logger.error('unable to parse current version \'{}\''
                                      'as an integer'.format(jambi_versions[0].ref))
                self.logger.info('your database is at version "{}"'.format(field))
            else:
                self.logger.info('this database hasn\'t been migrated yet')
        except ProgrammingError:
            self.logger.info('run \'init\' to create a jambi version table first')
        finally:
            self.db.close()
        return result

    def __set_version(self, ref):
        """sets the jambi table version

        Note that this does not run the migrations, but is instead used by
        the migration logic to easily set the version after migrations have
        completed.
        """
        JambiModel.delete().execute()
        JambiModel.create(ref=str(ref))
        self.logger.info('set jambi version to {}'.format(ref))

    def init(self):
        """initialize the jambi database version table"""
        self.db.connect()
        try:
            self.db.create_tables([JambiModel], safe=True)
            JambiModel.create(ref='0')
            self.logger.info('database initialized')
        except IntegrityError:
            self.logger.info('database was already initialized')
        self.db.close()

    def makemigration(self, template=None):
        """create a new migration from template and place in migrate location"""
        return NotImplemented

    def wish_from_kwargs(self, **kwargs):
        """Processes keyword arguments in to a jambi wish."""
        try:
            wish = kwargs.pop('wish')
        except KeyError:
            self.logger.error('there was no wish to process')

        if wish == 'upgrade':
            result = self.upgrade(kwargs.pop('ref', None))
        elif wish == 'inspect':
            result = self.inspect()
        elif wish == 'init':
            result = self.init()
        else:
            self.logger.error('unknown wish')
            result = None

        return result

    def __get_db_and_schema_from_config(self):
        _db.init(self.getconfig('database', 'database'),
                 user=self.getconfig('database', 'user'),
                 password=self.getconfig('database', 'password'),
                 host=self.getconfig('database', 'host'))
        _schema = self.getconfig('database', 'schema')
        return _db, _schema


if __name__ == '__main__':
    # parse arguments
    parser = argparse.ArgumentParser(description='Migration tools for the db.')
    subparsers = parser.add_subparsers(title='actions', dest='wish')

    wish_inspect = subparsers.add_parser('inspect', help='check database version')
    wish_inspect = subparsers.add_parser('init', help='create jambi table')

    wish_migrate = subparsers.add_parser('upgrade', help='run migrations')
    wish_migrate.add_argument('ref', type=str, help='reference hash')

    opts = parser.parse_args()

    if opts.wish is None:
        parser.print_help()
        sys.exit(1)

    # create jambi and process command
    jambi = Jambi()
    jambi.wish_from_kwargs(**vars(opts))

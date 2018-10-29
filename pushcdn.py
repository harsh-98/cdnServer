#!/usr/bin/env python

"""
pytograph - Reflect local filesystem changes on a remote system in real time, automatically.


Requires Python 2.7, and the third-party Python packages config, pysftp, and watchdog.
"""

from config import Config
from watchdog.observers import Observer
from watchdog.events import *
import argparse, getpass, logging, posixpath, pysftp, sys, time

logFormat='%(levelname)s: %(message)s'
logging.basicConfig(format=logFormat)
logger = logging.getLogger('pytograph')
logger.setLevel(logging.INFO)

class PytoWatchdogHandler(PatternMatchingEventHandler):
  """
  Watchdog event handler.
  Triggers appropriate actions on a remote server via a RemoteControl when
  specific Watchdog events are fired due to local filesystem changes.
  """

  def __init__(self, remote_control, **kw):
    super(PytoWatchdogHandler, self).__init__(**kw)
    self._remote_control = remote_control

  def on_created(self, event):
    if isinstance(event, DirCreatedEvent):
      # Ignoring this event for now since directories will automatically
      # be created on the remote server by transfer_file()
      logger.debug('Ignoring DirCreatedEvent for %s' % event.src_path)
    else:
      self._remote_control.transfer_file(event.src_path)

  def on_deleted(self, event):
    self._remote_control.delete_resource(event.src_path)

  def on_modified(self, event):
    if isinstance(event, DirModifiedEvent):
      logger.debug('Ignoring DirModifiedEvent for %s' % event.src_path)
    else:
      self._remote_control.transfer_file(event.src_path)

  def on_moved(self, event):
    self._remote_control.move_resource(event.src_path, event.dest_path)


class RemoteControl:
  """
  Performs filesystem manipulations on a remote server,
  using data from the local machine's filesystem as necessary.
  """

  def __init__(self, sftp_connection, local_base, remote_base):
    self._connection = sftp_connection.connection
    self._ssh_prefix = sftp_connection.ssh_prefix
    self._local_base = local_base
    self._remote_base = remote_base
    self._local_base_length = len(local_base)

  # Given a full canonical path on the local filesystem, returns an equivalent full
  # canonical path on the remote filesystem.
  def get_remote_path(self, local_path):
    # Strip the local base path from the local full canonical path to get the relative path
    # TODO: This will not work properly on Windows since slash directions will conflict
    remote_relative = local_path[self._local_base_length:]
    return self._remote_base + remote_relative

  def transfer_file(self, src_path):
    dest_path = self.get_remote_path(src_path)
    logger.info('Copying\n\t%s\nto\n\t%s:%s' % (src_path, self._ssh_prefix, dest_path))
    try:
      # Make sure the intermediate destination path to this file actually exists on the remote machine
      self._connection.execute('mkdir -p "' + os.path.split(dest_path)[0] + '"')
      self._connection.put(src_path, dest_path)
    except Exception as e:
      logger.error('Caught exception while copying:')
      logger.exception(e)

  def delete_resource(self, src_path):
    dest_path = self.get_remote_path(src_path)
    logger.info('Deleting %s:%s' % (self._ssh_prefix, dest_path))
    try:
      self._connection.execute('rm -rf "' + dest_path + '"')
    except Exception as e:
      logger.error('Caught exception while deleting:')
      logger.exception(e)

  def move_resource(self, src_path, dest_path):
    logger.info('Moving\n\t%s:%s\nto\n\t%s:%s' %
      (self._ssh_prefix, self.get_remote_path(src_path), self._ssh_prefix, self.get_remote_path(dest_path)))
    try:
      # Make sure the intermediate destination path to this file actually exists on the remote machine
      self._connection.execute('mkdir -p "' + os.path.split(dest_path)[0] + '"')
      self._connection.execute('mv "' + src_path + '" "' + dest_path + '"')
    except Exception as e:
      logger.error('Caught exception while moving:')
      logger.exception(e)


class SFTPConnection:
  """
  Maintains an SSH connection to a remote server via pysftp.
  """

  def __init__(self, host, port = None, private_key_file = None, private_key_password = None, username = None, password = None):

    self._ssh_prefix = None
    self._connection = None

    if username == '':
      username = getpass.getuser()
      logger.debug('No username configured; assuming username %s' % username)
    else:
      logger.debug('Using configured username %s' % username)

    self._ssh_prefix = '%s@%s' % (username, host)

    # Attempt key authentication if no password was specified; prompt for a password if it fails
    if password == '':
      try:
        logger.debug('No password specified, attempting to use key authentication')
        self._connection = pysftp.Connection(host, port = port, username = username, private_key = private_key_file, private_key_pass = private_key_password)
      except Exception as e:
        logger.debug('Key authentication failed.\nCause: %s\nFalling back to password authentication...' % e)
        password = getpass.getpass('Password for %s: ' % self._ssh_prefix)
    else:
      logger.debug('Using configured password')

    # If we don't have a connection yet, attempt password authentication
    if self._connection is None:
      try:
        self._connection = pysftp.Connection(host, port = port, username = username, password = password)
      except Exception as e:
        logger.error('Could not successfully connect to %s\nCause: %s' % (self._ssh_prefix, e))
        sys.exit(1)

    logger.debug('Successfully connected to %s' % self._ssh_prefix)

  @property
  def ssh_prefix(self):
    """
    (Read-only)
    String containing the username and host information for the remote server.
    """
    return self._ssh_prefix

  @property
  def connection(self):
    """
    (Read-only)
    A pysftp Connection object representing the active connection to the remote server.
    """
    return self._connection


def _main():

  # Cannot use argparse.FileType with a default value since the help message will not display if pytograph.cfg
  # doesn't appear in the default location. Could subclass argparse.FileType but the following seems more intuitive.
  # See http://stackoverflow.com/questions/8236954/specifying-default-filenames-with-argparse-but-not-opening-them-on-help
  parser = argparse.ArgumentParser(description='Reflect local filesystem changes on a remote system in real time, automatically.')
  parser.add_argument('-c', '--config-file', default='pytograph.cfg', help='location of a pytograph configuration file')
  args = parser.parse_args()
  print(args.config_file)
  try:
    config_file = open(args.config_file,'r')
  except Exception as e:
    logger.error('Couldn\'t read pytograph configuration file!\n\
Either place a pytograph.cfg file in the same folder as pytograph.py, or specify an alternate location.\n\
Run \'%s -h\' for usage information.\nCause: %s' % (os.path.basename(__file__), e))
    sys.exit(1)

  try:
    cfg = Config(config_file)
  except Exception as e:
    logger.error('Pytograph configuration file is invalid!\nCause: %s' % e)
    sys.exit(1)

  # Read configuration
  local_root_path = os.path.abspath(os.path.expanduser(cfg.local_root_path))
  if not os.path.isdir(local_root_path):
    logger.error('Invalid local_root_path configured: %s is not a valid path on the local machine' % cfg.local_root_path)
    sys.exit(1)
  else:
    logger.debug('Using local root path: ' + local_root_path)

  # Create persistent SSH connection to remote server
  sftp_connection = SFTPConnection(cfg.remote_host, cfg.remote_port, cfg.private_key_file, cfg.private_key_password, cfg.remote_username, cfg.remote_password)

  logger.debug('Initializating path mappings...')

  # If this is still true when the loop below completes, no valid mappings are configured.
  no_valid_mappings = True

  observer = Observer()

  for mapping in cfg.path_mappings:

    # Create an absolute local path from the local root path and this mapping's local relative path
    local_base = os.path.join(local_root_path, mapping.local)
    if not os.path.isdir(local_base):
      logger.warn('Invalid path mapping configured: %s is not a valid path on the local machine' % local_base)
      continue

    # If we got this far, we have at least one valid mapping
    no_valid_mappings = False

    # Create an absolute remote path from the remote root path and this mapping's remote relative path
    # Use explicit posixpath.join since the remote server will always use UNIX-style paths for SFTP
    # TODO: Validate this, expand tilde notation, etc.
    remote_base = posixpath.join(cfg.remote_root_path, mapping.remote)

    logger.info('Path mapping initializing:\nChanges at local path\n\t%s\nwill be reflected at remote path\n\t%s:%s'
      % (local_base, sftp_connection.ssh_prefix, remote_base))

    # Create necessary objects for this particular mapping and schedule this mapping on the Watchdog observer as appropriate
    remote_control = RemoteControl(sftp_connection = sftp_connection, local_base = local_base, remote_base = remote_base)
    event_handler = PytoWatchdogHandler(ignore_patterns = cfg.ignore_patterns, remote_control = remote_control)
    observer.schedule(event_handler, path=local_base, recursive=True)

  if no_valid_mappings:
    logger.error('No valid path mappings were configured, so there\'s nothing to do. Please check your pytograph configuration file.')
    sys.exit('Terminating.')

  # We have at least one valid mapping, so start the Watchdog observer - filesystem monitoring actually begins here
  observer.start()

  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    observer.stop()
  observer.join()

if __name__ == "__main__":

  _main()


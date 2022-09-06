#  Copyright 2019-2022 Jareth Lomson <jareth.lomson@gmail.com>
#  This file is part of OneDrive Client Program which is released under MIT License
#  See file LICENSE for full license details
import logging
import math
import os
import sys
from abc import ABC, abstractmethod
from beartype import beartype
from lib.graph_helper import MsGraphClient
from lib.datetime_helper import str_from_ms_datetime

lg = logging.getLogger('odc.msobject')


class StrPathUtil:
  __TO_BE_ESCAPED = ('\\', ' ', '\'') if sys.platform != "win32" else (
      ' ')  # \\ MUST be the first one

  @staticmethod
  def escape_str(what):
    result = what
    for c in StrPathUtil.__TO_BE_ESCAPED:
      result = result.replace(c, f"\\{c}")

    return result

  @staticmethod
  def split_path(full_path):
    fp = full_path
    # fp = shlex.split(full_path)[0]  # remove quote and escape sequence
    fp = os.path.normpath(fp)
    result = []
    while (fp != os.sep) and (fp != ""):
      parts = os.path.split(fp)
      fp = parts[0]
      result.append(parts[1])
    if fp != "":         # Append root path if available
      result.append("")
    result.reverse()
    return result

  @staticmethod
  def test():
    ip = input("> ")
    print(f"result = {StrPathUtil.escape_str(ip)}")


class MsObject(ABC):

  @property
  @abstractmethod
  def id():
    pass

  @property
  @abstractmethod
  def path():
    pass

  @property
  @abstractmethod
  def name():
    pass

  @abstractmethod
  def str_full_details(self):
    pass

  @property
  def __isabstractmethod__(self):
    return any(getattr(f, '__isabstractmethod__', False) for
               f in (self._fget, self._fset, self._fdel))

  @staticmethod
  def get_lastfolderinfo_path(root_fi, input, current_fi=None):
    """
      Return a tuple (<last_folder_info_path>, <remaining_text>)
    """
    my_input = input

    # Manage empty path
    if my_input == "":
      if current_fi is None:
        return (None, None)
      else:
        return (current_fi, "")

     # Manage relative path without current_fi
    if my_input[0] != "/" and current_fi is None:
      return (None, None)

    # Build full path and normalize it (removing .. and .)
    if my_input[0] != "/":
      my_input = f"{current_fi.path}/{my_input}"
    my_input = os.path.normpath(my_input)

    # Search folder and extract start_text
    folder_names = StrPathUtil.split_path(my_input)
    folder_names = folder_names[1:]  # Remove first item which is ""
    if input[-1] == "/":  # Last part is a folder
      start_text = ""
    else:
      start_text = folder_names[-1]
      # remove the last folder name which is the start text
      folder_names = folder_names[:-1]

    search_folder = root_fi
    found = True
    for f in folder_names:
      if search_folder.is_direct_child_folder(f, True):
        search_folder = search_folder.get_direct_child_folder(f, True)
      else:
        found = False
        break

    if found:
      return (search_folder, start_text)
    else:
      return (None, None)


class MsFolderInfo(MsObject):

  @beartype
  def __init__(
          self,
          name: str,
          full_path: str,
          mgc: MsGraphClient,
          id: str = "0",
          child_count: int = None,
          size: int = None,
          parent=None,
          lmdt=None,
          cdt=None):
    """
        Init folder info
        mgc   = MsGraphClient
    """
    self.__id = id
    self.__full_path = full_path
    self.__name = name
    self.__mgc = mgc
    self.children_file = []
    self.children_folder = []
    self.__dict_children_file = {}
    self.__dict_children_folder = {}
    self.next_link_children = None

    self.parent = parent
    self.child_count = child_count
    self.size = size

    self.__children_files_retrieval_status = None    # None,"partial" or "all"
    self.__children_folders_retrieval_status = None  # None, "partial" or "all"

    self.last_modified_datetime = lmdt
    self.creation_datetime = cdt

  def get_full_path(self):
    return self.__full_path
  path = property(get_full_path)

  def _get_id(self):
    return self.__id
  id = property(_get_id)

  def _get_name(self):
    return self.__name
  name = property(_get_name)

  def retrieve_children_info(
          self,
          only_folders=False,
          recursive=False,
          depth=999):
    lg.debug(
        f"[retrieve_children_info] {self.get_full_path()} - only_folders = {only_folders} - depth = {depth}")

    if depth > 0 and (
        only_folders and not self.folders_retrieval_has_started()
        or not self.files_retrieval_has_started() or not self.folders_retrieval_has_started()
    ):

      (ms_response, next_link) = self.__mgc.get_ms_response_for_children_folder_path(
          self.get_full_path(), only_folders)
      self.next_link_children = next_link

      for c in ms_response:
        isFolder = 'folder' in c
        if isFolder and not self.folders_retrieval_has_started():
          fi = ObjectInfoFactory.MsFolderFromMgcResponse(self.__mgc, c, self)
          self.add_folder_info(fi)
          if recursive:
            fi.retrieve_children_info(
                only_folders=only_folders,
                recursive=recursive,
                depth=depth - 1)

        elif not only_folders and not isFolder:
          fi = ObjectInfoFactory.MsFileInfoFromMgcResponse(self.__mgc, c)
          self.add_file_info(fi)
        else:
          lg.info("retrieve_children_info : UNKNOWN RESPONSE")

      self.__add_default_folder_info()
      lg.debug(
          f"[retrieve_children_info] {self.get_full_path()} - setting retrieval status")

      if not only_folders:
        self.__children_files_retrieval_status = "partial" if self.next_link_children is not None else "all"

      self.__children_folders_retrieval_status = "partial" if self.next_link_children is not None else "all"

  def retrieve_children_info_next(
          self,
          only_folders=False,
          recursive=False,
          depth=999):
    lg.debug(
        f"[retrieve_children_info_next] {self.get_full_path()} - only_folders = {only_folders} - depth = {depth}")

    if depth > 0 and (
        only_folders and not self.__children_folders_retrieval_status != "all"
        or self.__children_folders_retrieval_status != "all"
    ):

      (ms_response, next_link) = self.__mgc.get_ms_response_for_children_folder_path_from_link(
          self.next_link_children, only_folders)
      self.next_link_children = next_link

      for c in ms_response:
        isFolder = 'folder' in c
        if isFolder:
          fi = ObjectInfoFactory.MsFolderFromMgcResponse(self.__mgc, c, self)
          self.add_folder_info(fi)
          if recursive:
            fi.retrieve_children_info(
                only_folders=only_folders,
                recursive=recursive,
                depth=depth - 1)

        elif not only_folders and not isFolder:
          fi = ObjectInfoFactory.MsFileInfoFromMgcResponse(self.__mgc, c)
          self.add_file_info(fi)
        else:
          lg.info("retrieve_children_info : UNKNOWN RESPONSE")

      lg.debug(
          f"[retrieve_children_info_from_link] {self.next_link_children} - setting retrieval status")

      if not only_folders:
        self.__children_files_retrieval_status = "partial" if self.next_link_children is not None else "all"

      self.__children_folders_retrieval_status = "partial" if self.next_link_children is not None else "all"

  def create_empty_subfolder(self, folder_name):
    creation_ok = self.__mgc.create_folder(self.get_full_path(), folder_name)
    if creation_ok:
      new_folder_info = MsFolderInfo(
          folder_name,
          "{0}/{1}".format(self.get_full_path(), folder_name),
          self.__mgc,
          parent=self)
      self.add_folder_info(new_folder_info)
      if self.child_count is not None:
        self.child_count += 1
      return new_folder_info
    else:
      return None

  def add_folder_info(self, folder_info):
    self.children_folder.append(folder_info)
    self.__dict_children_folder[folder_info.name] = folder_info

  def __add_default_folder_info(self):
    # add subfolder "." and "..""
    self.__dict_children_folder["."] = self
    self.__dict_children_folder[".."] = self.parent

  def add_file_info(self, file_info):
    self.children_file.append(file_info)
    self.__dict_children_file[file_info.name] = file_info

  def get_direct_child_folder(
          self,
          folder_name,
          force_children_retrieval=False):
    if force_children_retrieval and not self.folders_retrieval_has_started():
      self.retrieve_children_info(only_folders=True)
    return self.__dict_children_folder[folder_name] if folder_name in self.__dict_children_folder else None

  def get_child_folder(self, folder_path, force_children_retrieval=False):
    path_parts = folder_path.split(os.sep)
    if path_parts[-1] == "":      # folder_path ends with a "/"
      path_parts = path_parts[:-1]
    search_folder = self
    for f in path_parts:
      if search_folder.is_direct_child_folder(f, force_children_retrieval):
        search_folder = search_folder.get_direct_child_folder(
            f, force_children_retrieval)
      else:
        return None
    return search_folder

  def get_direct_child_file(self, file_name, force_children_retrieval=False):
    if force_children_retrieval and not self.folders_retrieval_has_started():
      self.retrieve_children_info(only_folders=False)
    return self.__dict_children_file[file_name] if file_name in self.__dict_children_file else None

  def get_child_file(self, file_path, force_children_retrieval=False):
    path_parts = file_path.split(os.sep)
    search_folder = self
    i = 0
    while i < (len(path_parts) - 1):
      f = path_parts[i]
      if search_folder.is_direct_child_folder(f, force_children_retrieval):
        search_folder = search_folder.get_direct_child_folder(
            f, force_children_retrieval)
      else:
        return None
      i += 1
    if search_folder.is_direct_child_file(
            path_parts[-1], force_children_retrieval):
      return search_folder.get_direct_child_file(
          path_parts[-1], force_children_retrieval)

  def is_direct_child_folder(
          self,
          folder_name,
          force_children_retrieval=False):
    if force_children_retrieval and not self.folders_retrieval_has_started():
      self.retrieve_children_info(only_folders=True)
    return folder_name in self.__dict_children_folder

  def is_child_folder(self, folder_path, force_children_retrieval=False):
    return self.get_child_folder(
        folder_path, force_children_retrieval) is not None

  def is_direct_child_file(self, file_name, force_children_retrieval=False):
    if force_children_retrieval and not self.folders_retrieval_has_started():
      self.retrieve_children_info(only_folders=False)
    return file_name in self.__dict_children_file

  def is_child_file(self, file_path, force_children_retrieval=False):
    return self.get_child_file(file_path, force_children_retrieval) is not None

  def files_retrieval_has_started(self):
    return self.__children_files_retrieval_status == "all" or self.__children_files_retrieval_status == "partial"

  def folders_retrieval_has_started(self):
    return self.__children_folders_retrieval_status == "all" or self.__children_folders_retrieval_status == "partial"

  def files_retrieval_is_completed(self):
    return self.__children_files_retrieval_status == "all"

  def folders_retrieval_is_completed(self):
    return self.__children_folders_retrieval_status == "all"

  def __str__(self):
    status_subfolders = "<subfolders ok>" if self.folders_retrieval_has_started() else ""
    status_subfiles = "<subfiles ok>" if self.files_retrieval_has_started() else ""

    fname = f"{self.name}/" if len(self.name) < 25 else f"{self.name[:20]}.../"
    result = f"{self.size:>20,}  {fname:<25}  {self.child_count:>6}  {status_subfolders}{status_subfiles}"
    return result

  def str_full_details(self):
    result = (
        f"Folder - {self.get_full_path()[1:]}\n"
        f"  name                            = {self.name}\n"
        f"  id                              = {self.__id}\n"
        f"  size                            = {self.size}\n"
        f"  childcount                      = {self.child_count}\n"
        f"  lastModifiedDateTime            = {self.last_modified_datetime}\n"
        f"  creationDateTime                = {self.creation_datetime}\n"
        f"  childrenFilesRetrievalStatus    = {self.__children_files_retrieval_status}\n"
        f"  childrenFoldersRetrievalStatus  = {self.__children_folders_retrieval_status}\n")

    return result

  def __repr__(self):
    return f"Folder({self.name})"


class MsFileInfo(MsObject):
  def __init__(
          self,
          name,
          parent_path,
          mgc,
          file_id,
          size,
          qxh,
          s1h,
          cdt,
          lmdt):
    # qxh = quickxorhash
    self.mgc = mgc
    self.__name = name
    self.__parent_path = parent_path
    self.__id = file_id
    self.size = size
    self.sha1hash = s1h
    self.qxh = qxh
    self.creation_datetime = cdt
    self.last_modified_datetime = lmdt

  def _get_path(self):
    return "/{0}/{1}".format(self.__parent_path, self.__name)
  path = property(_get_path)

  def _get_id(self):
    return self.__id
  id = property(_get_id)

  def _get_name(self):
    return self.__name
  name = property(_get_name)

  def __str__(self):
    fname = f"{self.name}" if len(self.name) < 45 else f"{self.name[:40]}..."
    fmdt = self.last_modified_datetime.strftime("%Y-%m-%d %H:%M:%S")
    result = f"{self.size:>20,}  {fname:<45}  {fmdt}  "
    return result

  def str_full_details(self):
    result = (
        "File - '{0}'\n"
        "  name                  = {1}\n"
        "  full_path             = {2}\n"
        "  id                    = {3:>20}\n"
        "  size                  = {4:,}\n"
        "  quickXorHash          = {5}\n"
        "  sha1Hash              = {6}\n"
        "  creationDateTime      = {7}\n"
        "  lastModifiedDateTime  = {8}"
    ).format(
        self.name,
        self.name,
        self.path,
        self.__id,
        self.size,
        self.qxh,
        self.sha1hash,
        self.creation_datetime,
        self.last_modified_datetime)

    return result

  def __repr__(self):
    return f"File({self.name})"


class ObjectInfoFactory:

  @staticmethod
  def get_object_info(mgc, path):
    """
      Return a 2-tuple (<error_code>, <object_info>).
      If error_code is not None, object is None and error_code is set code of response sent by Msgraph.
      Else, object_info is set with found object or None if nothing is found.
    """
    prefixed_path = "" if path == "/" or path == "" else f":/{path}"  # Consider root
    r = mgc.mgc.get('{0}/me/drive/root{1}'.format(
        MsGraphClient.graph_url, prefixed_path
    )).json()
    if 'error' in r:
      return (r['error']['code'], None)

    if ('folder' in r):
      # import pprint
      # pprint.pprint(mgc_response_json)
      mso = ObjectInfoFactory.MsFolderFromMgcResponse(mgc, r)
    else:
      mso = ObjectInfoFactory.MsFileInfoFromMgcResponse(mgc, r)
    return (None, mso)

  @staticmethod
  def MsFolderFromMgcResponse(mgc, mgc_response_json, parent=None):

    # Workaround following what seems to be a bug. Space is replaced by "%20" sequence
    #   in mgc_response when parent name contains a space
    if parent is not None:
      parent_path = parent.get_full_path()
    else:
      if 'parentReference' in mgc_response_json and 'path' in mgc_response_json[
              'parentReference']:
        parent_path = mgc_response_json['parentReference']['path'][12:]
      else:
        parent_path = ""

    full_path = "" if "root" in mgc_response_json else f"{parent_path}/{mgc_response_json['name']}"
    return MsFolderInfo(
        full_path=full_path,
        name=mgc_response_json['name'],
        mgc=mgc,
        id=mgc_response_json['id'],
        child_count=mgc_response_json['folder']['childCount'],
        size=mgc_response_json['size'],
        parent=parent,
        lmdt=str_from_ms_datetime(mgc_response_json['lastModifiedDateTime']),
        cdt=str_from_ms_datetime(mgc_response_json['createdDateTime'])
    )

  @staticmethod
  def MsFileInfoFromMgcResponse(mgc, mgc_response_json):
    if 'quickXorHash' in mgc_response_json['file']['hashes']:
      qxh = mgc_response_json['file']['hashes']['quickXorHash']
    else:
      qxh = None
    return MsFileInfo(mgc_response_json['name'],
                      mgc_response_json['parentReference']['path'][13:],
                      mgc,
                      mgc_response_json['id'],
                      mgc_response_json['size'],
                      qxh,
                      mgc_response_json['file']['hashes']['sha1Hash'],
                      str_from_ms_datetime(mgc_response_json['createdDateTime']),
                      str_from_ms_datetime(mgc_response_json['lastModifiedDateTime'])
                      )

"""Independent GIO consumer emulating file-manager trash actions in fixtures."""
from pathlib import Path
import json
from gi.repository import Gio, GLib
from mio_linux.system_trash import SystemTrash, bounded
from mio_linux.recovery import directory

ATTRS = 'standard::name,standard::type,standard::size,trash::orig-path,trash::deletion-date,id::file,time::modified,time::modified-usec,etag::value'


def fingerprint(info):
    return [info.get_attribute_byte_string('trash::orig-path'),
            info.get_attribute_string('trash::deletion-date'),
            info.get_attribute_string('id::file'), info.get_size(),
            info.get_attribute_uint64('time::modified'),
            info.get_attribute_uint32('time::modified-usec'),
            int(info.get_file_type()), info.get_etag()]


class TrashProbe(SystemTrash):
    def __init__(self):
        self.root = Gio.File.new_for_uri('trash:///')
        try:
            self.monitor = self.root.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        except GLib.Error:
            self.monitor = None  # records() reports unavailable GVfs explicitly.

    def records(self):
        result = []
        with bounded() as cancel:
            children = self.root.enumerate_children(ATTRS, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancel)
            try:
                while info := children.next_file(cancel):
                    if len(result) >= 20000:
                        raise ValueError('回收站超过 20,000 项，请在文件管理器中处理后刷新')
                    original = info.get_attribute_byte_string('trash::orig-path')
                    if not original or not Path(original).is_absolute():
                        raise ValueError('系统回收站存在缺少原始路径的项目，请在文件管理器检查')
                    source = self.root.get_child(info.get_name())
                    token = json.dumps([source.get_uri(), fingerprint(info)], ensure_ascii=True)
                    result.append({'id': token, 'path': original, 'time': info.get_attribute_string('trash::deletion-date') or '',
                                   'stamp': (0, 0, info.get_size()),
                                   'is_dir': info.get_file_type() == Gio.FileType.DIRECTORY})
            finally:
                children.close(None)
        return sorted(result, key=lambda item: item['time'], reverse=True)

    def checked(self, token, cancel):
        uri, expected = json.loads(token)
        source = Gio.File.new_for_uri(uri)
        if not source.get_parent() or not source.get_parent().equal(self.root):
            raise ValueError('只能处理系统回收站顶层项目')
        info = source.query_info(ATTRS, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancel)
        if fingerprint(info) != expected:
            raise ValueError('回收项目已变化，请刷新后重新审阅')
        return source, info

    def restore(self, token):
        with bounded() as cancel:
            source, info = self.checked(token, cancel)
            path = Path(info.get_attribute_byte_string('trash::orig-path'))
            # No symlink ancestors and no overwrite; missing parent stays actionable.
            with directory(path.parent):
                source.move(Gio.File.new_for_path(str(path)),
                            Gio.FileCopyFlags.NOFOLLOW_SYMLINKS | Gio.FileCopyFlags.NO_FALLBACK_FOR_MOVE,
                            cancel, None, None)

    def erase(self, token):
        with bounded() as cancel:
            source, _ = self.checked(token, cancel)
            # GVfs owns recursive trash deletion, including directory entries.
            # A symlink is removed as a link; its target is never traversed by Mio.
            source.delete(cancel)


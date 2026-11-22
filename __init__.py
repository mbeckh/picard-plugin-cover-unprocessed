# Copyright 2026 Michael Beckh (mbeckh)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cover Art Provider which prefers local thumbnail files (which are not re-processed).

Also show unprocessed covers in the UI, save them to a file and rename them automatically.
"""

from __future__ import annotations

from html import escape
import itertools
from pathlib import Path
import re
import threading
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    cast,
    override,
)

from PyQt6 import (
    QtCore,
    QtGui,
    QtWidgets,
)

from picard.const.cover_processing import ImageFormat
from picard.coverart import (
    CoverArtImageIOError,
    CoverArtImageProcessing,
)
from picard.coverart.image import (
    ImageInfo,
    TagCoverArtImage,
)
from picard.coverart.providers import CoverArtProviderLocal
from picard.coverart.providers.local import LocalFileCoverArtImage
from picard.metadata import Metadata
from picard.plugin3.api import (
    CoverArtImage,
    CoverArtProvider,
    DebugOpt,
    File,
    PageOptionConfigs,
    PluginApi,
    ProviderOptions,
    t_,
)
from picard.util import scripttofilename
from picard.util.datahash import DataHash
from picard.util.imageinfo import identify

from picard.ui.infodialog import InfoDialog
from picard.ui.infodialog.widgets import (
    ArtworkCoverWidget,
    ArtworkTable,
)

from . import monkey
from .ui_compiled.ui_cover_options import Ui_UnprocessedCoverArtProviderOptions


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


_api: PluginApi


def _is_enabled() -> bool:
    """Check if provider is enabled.

    Returns:
        True if the cover provider is enabled, else False.
    """
    return bool(
        True
        for name, enabled in _api.global_config.setting['ca_providers']
        if enabled and name == UnprocessedCoverArtProvider.NAME
    )


#
# Additional functions and properties for CoverArtImage.
#
class _CoverArtImageWithUnprocessed(CoverArtImage):
    _uc_unprocessed: bytes | None
    _uc_unprocessed_filepath: str
    _uc_has_unprocessed_filepath: bool
    _uc_has_unprocessed_data: bool
    _uc_unprocessed_reset: Callable[[], None]
    # if any, only one of the followsing properties is set
    _uc_unprocessed_data: DataHash
    _uc_unprocessed_filepath_str: str


_unprocessed_cover_lock = threading.Lock()


def _get_unprocessed_filepath(self: _CoverArtImageWithUnprocessed) -> str | None:
    """Get filepath of unprocessed data.

    Could be local file, unprocessed remote image etc.

    Returns:
        A path which can be used to load unprocessed data.
    """
    if self._uc_has_unprocessed_filepath:
        return self._uc_unprocessed_filepath_str
    if isinstance(self, LocalFileCoverArtImage):
        return self.url.toLocalFile() if self.url else None
    if self.datahash:
        return self.datahash.filename
    return None


def _set_unprocessed_filepath(self: _CoverArtImageWithUnprocessed, unprocessed_filepath: str) -> None:
    """Set path of unprocessed data.

    Raises:
        ValueError: If either unprocessed path or data have already been set.
    """
    if self._uc_has_unprocessed_filepath:
        raise ValueError("Unprocessed path already set.")
    if self._uc_has_unprocessed_data:
        raise ValueError("Unprocessed data already set.")
    if unprocessed_filepath:
        self._uc_unprocessed_filepath_str = unprocessed_filepath


def _has_unprocessed_filepath(self: _CoverArtImageWithUnprocessed) -> bool:
    """Check for presence of unprocessed data in a file (in contrast to e.g. data hash).

    Returns:
        True if a dedicated unprocessed path has been set.
    """
    return hasattr(self, '_uc_unprocessed_filepath_str')


def _has_unprocessed_data(self: _CoverArtImageWithUnprocessed) -> bool:
    """Check if image has unprocessed data in a hash (in contrast to a local file).

    Returns:
        True if there is data in a hash.
    """
    return hasattr(self, '_uc_unprocessed_data')


def _set_unprocessed(self: _CoverArtImageWithUnprocessed, unprocessed_data: bytes) -> None:
    """Set data as a data hash.

    Raises:
        ValueError: If unprocessed path has already been set.
    """
    if self._uc_has_unprocessed_filepath:
        raise ValueError("Unprocessed path already set.")
    if isinstance(self, LocalFileCoverArtImage):
        # file exists, no need for DataHash
        return
    with _unprocessed_cover_lock:
        # do not overwrite
        if not self._uc_has_unprocessed_data:
            self._uc_unprocessed_data = DataHash(unprocessed_data)


def _get_unprocessed(self: _CoverArtImageWithUnprocessed) -> bytes | None:
    """Get unprocessed data, which could be read from local file, from a data hash etc.

    Returns:
        Data of an unprocessed image.
    """
    if self._uc_has_unprocessed_filepath:
        return Path(self._uc_unprocessed_filepath_str).read_bytes()
    if isinstance(self, LocalFileCoverArtImage):
        return Path(self.url.toLocalFile()).read_bytes() if self.url else None
    with _unprocessed_cover_lock:
        if self._uc_has_unprocessed_data:
            return self._uc_unprocessed_data.data()
    return self.data


def _unprocessed_reset(self: _CoverArtImageWithUnprocessed) -> None:
    """Reset any information about unprocessed data."""
    if self._uc_has_unprocessed_filepath:
        del self._uc_unprocessed_filepath_str
    if self._uc_has_unprocessed_data:
        del self._uc_unprocessed_data


type.__setattr__(CoverArtImage, '_uc_unprocessed', property(fget=_get_unprocessed, fset=_set_unprocessed))  # ruff: ignore[unnecessary-dunder-call]
type.__setattr__(  # ruff: ignore[unnecessary-dunder-call]
    CoverArtImage, '_uc_unprocessed_filepath', property(fget=_get_unprocessed_filepath, fset=_set_unprocessed_filepath)
)
type.__setattr__(CoverArtImage, '_uc_has_unprocessed_filepath', property(fget=_has_unprocessed_filepath))  # ruff: ignore[unnecessary-dunder-call]
type.__setattr__(CoverArtImage, '_uc_has_unprocessed_data', property(fget=_has_unprocessed_data))  # ruff: ignore[unnecessary-dunder-call]
type.__setattr__(CoverArtImage, '._uc_unprocessed_reset', _unprocessed_reset)  # ruff: ignore[unnecessary-dunder-call]


#
# Show unprocessed cover in InfoDialog.
#


class CoverArtImageWrapper(CoverArtImage):
    """Wrapper to supply image to InfoDialog."""

    @override
    def __init__(self, covertartimage: CoverArtImage) -> None:
        self._wrapped = cast('_CoverArtImageWithUnprocessed', covertartimage)
        self._data = self._wrapped._uc_unprocessed
        self._info = identify(self._data) if self._data else None

    def __getattr__(self, name: str) -> Any:  # ruff: ignore[any-type]
        """Forward any attribute access to the wrapped class.

        Returns:
            Attribute of wrapped object.
        """
        return getattr(self._wrapped, name)

    @property
    @override
    def data(self) -> bytes | None:
        return self._data

    @property
    @override
    def source(self) -> str:
        wrapped = self._wrapped
        if wrapped.url is not None:
            return f"{wrapped.sourceprefix}: {wrapped._uc_unprocessed_filepath}"
        return f"{wrapped.sourceprefix}"

    @property
    @override
    def tempfile_filename(self) -> str | None:
        wrapped = self._wrapped
        return wrapped._uc_unprocessed_filepath

    @property
    @override
    def datalength(self) -> int:
        return self._info.datalen if self._info else 0

    @property
    @override
    def width(self) -> int:
        return self._info.width if self._info else 0

    @property
    @override
    def height(self) -> int:
        return self._info.height if self._info else 0

    @property
    @override
    def mimetype(self) -> str | None:
        return self._info.format_info.mime if self._info and self._info.format_info else ''


@monkey.patch(InfoDialog, InfoDialog._display_artwork_image_cell)
def _monkey_InfoDialog_display_artwork_image_cell(
    wrapped: Callable[[InfoDialog, int, str], None], self: InfoDialog, row_index: int, colname: str
) -> None:
    if colname == '_uc_unprocessed':
        col_index = self.artwork_table.get_column_index(colname)
        row = self.artwork_rows[row_index]
        filename = None
        image: CoverArtImage | None = getattr(row, 'new_image', None)
        if not image:
            image = getattr(row, 'orig_image', None)

        if isinstance(image, LocalFileCoverArtImage):
            filename = cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed_filepath
            if filename:
                filename = Path(filename).name

        pixmap = None
        infos = None
        item = QtWidgets.QTableWidgetItem()

        if image:
            try:
                image = CoverArtImageWrapper(image)
                data = image.data
                if data:
                    pixmap = QtGui.QPixmap()
                    pixmap.loadFromData(data)
                    tooltip_message = _api.tr(
                        'ui.infodialog.image.unprocessed.tooltip', "Double-click to open in external viewer"
                    )
                    item.setToolTip(self._artwork_tooltip(tooltip_message, image))
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, image)
            except CoverArtImageIOError:
                _api.logger.exception("Error loading unprocessed image.")
                pixmap = self._pixmaps['missing']
                item.setToolTip(
                    self._artwork_tooltip(
                        _api.tr('ui.infodialog.image.missing.tooltip', "Missing temporary file"), image
                    )
                )
        infos = "<br />".join(
            escape(t) for t in itertools.chain([filename], self._artwork_infos(image)) if t is not None
        )

        img_wgt = ArtworkCoverWidget(pixmap=pixmap, text=infos)
        self.artwork_table.setCellWidget(row_index, col_index, img_wgt)
        self.artwork_table.setItem(row_index, col_index, item)
        return

    wrapped(self, row_index, colname)


#
# Add column to InfoDialog
# PATCH: picard.ui.infodialog.widgets.ArtworkTable (and all subclasses)
#
def _get_all_subclasses(cls: type) -> Iterator[type]:
    yield cls
    for sub in cls.__subclasses__():
        yield from _get_all_subclasses(sub)


def _add_infodialog_column() -> None:
    for cls in _get_all_subclasses(ArtworkTable):
        if hasattr(cls._columns, '_uc_unprocessed'):
            return

        if 'NUM_COLS' in cls.__dict__:
            cls.NUM_COLS += 1
        if '_columns' in cls.__dict__:
            cls._columns['_uc_unprocessed'] = len(cls._columns)
        if 'artwork_columns' in cls.__dict__:
            cls.artwork_columns += ('_uc_unprocessed',)
        if '_labels' in cls.__dict__:
            cls._labels += (_api.tr('ui.infodialog.header.unprocessed.title', "Unprocessed"),)
        if '_tooltips' in cls.__dict__:
            cls._tooltips['_uc_unprocessed'] = _api.tr(
                'ui.infodialog.header.unprocessed.tooltip', "Unprocessed cover art"
            )


def _remove_infodialog_column() -> None:
    for cls in _get_all_subclasses(ArtworkTable):
        if not hasattr(cls._columns, '_uc_unprocessed'):
            return

        if 'NUM_COLS' in cls.__dict__:
            cls.NUM_COLS -= 1
        if '_columns' in cls.__dict__:
            del cls._columns['_uc_unprocessed']
        if 'artwork_columns' in cls.__dict__:
            cls.artwork_columns = cls.artwork_columns[:-1]
        if '_labels' in cls.__dict__:
            cls._labels = cls._labels[:-1]
        if '_tooltips' in cls.__dict__:
            del cls._tooltips['_uc_unprocessed']


class UnprocessedCoverArtProviderOptions(ProviderOptions):
    """Searches for local files and prefers thumbnails (which are not re-processed).

    Adds unprocessed filepath (from possibly unrelated file!) to those CovertArtImage objects.
    """

    _options_ui = Ui_UnprocessedCoverArtProviderOptions
    ui: Ui_UnprocessedCoverArtProviderOptions

    OPTIONS: ClassVar[PageOptionConfigs] = {
        'cover_thumbnail_regex': {'widgets': ['thumbnail_regex']},
        'cover_unprocessed_regex': {'widgets': ['unprocessed_regex']},
        'cover_unprocessed_name': {'widgets': ['unprocessed_name']},
    }

    @override
    def load(self) -> None:
        plugin_config = self.api.plugin_config
        self.ui.thumbnail_regex.setText(plugin_config['cover_thumbnail_regex'])
        self.ui.unprocessed_regex.setText(plugin_config['cover_unprocessed_regex'])
        self.ui.unprocessed_name.setPlainText(plugin_config['cover_unprocessed_name'])

    @override
    def save(self) -> None:
        plugin_config = self.api.plugin_config
        plugin_config['cover_thumbnail_regex'] = self.ui.thumbnail_regex.text()
        plugin_config['cover_unprocessed_regex'] = self.ui.unprocessed_regex.text()
        plugin_config['cover_unprocessed_name'] = self.ui.unprocessed_name.toPlainText().strip()


# Gets sorting info for cover (first front, then image and date size, name last).
_FILE_TYPE_ORDER = (
    ImageFormat.JPEG,
    ImageFormat.WEBP,
    ImageFormat.TIFF,
    ImageFormat.PNG,
    ImageFormat.GIF,
    ImageFormat.PDF,
)


def _cover_order(image: LocalFileCoverArtImage) -> tuple[bool, int, int, int, str]:
    """Get sort order for cover images (front first, then file type, the larger and bigger files).

    Returns:
        A tuple that can be used for sorting (in ascending order).
    """
    if not image.url:
        return (True, len(_FILE_TYPE_ORDER) + 1, 0, 0, '')
    filepath = image.url.toLocalFile()
    info = identify(Path(filepath).read_bytes())

    try:
        index = _FILE_TYPE_ORDER.index(info.format_info)
    except ValueError:
        index = len(_FILE_TYPE_ORDER)

    return (
        not image.is_front_image(),  # False comes before True when sorting bool
        index,
        -info.width * info.height,  # bigger image size first
        -info.datalen,  # bigger files first
        filepath,  # for guaranteed stable sorting
    )


class UnprocessedCoverArtProvider(CoverArtProvider, CoverArtProviderLocal):  # CoverArtProvider is from API
    """CovertArtProvider for preferring processed thumbnails and adding unprocessed data."""

    NAME = 'cover_unprocessed'
    TITLE = t_('ui.provider.title', "Local Files (prefer Thumbnails)")
    OPTIONS = UnprocessedCoverArtProviderOptions

    def _search_images(self, regex: str) -> Iterator[LocalFileCoverArtImage]:
        if regex:
            match_re = re.compile(regex, re.IGNORECASE)
            dirs_done = set()

            for file in self.album.iterfiles():
                current_dir = Path(file.filename).parent
                if current_dir in dirs_done:
                    continue
                dirs_done.add(current_dir)
                yield from self.find_local_images(current_dir, match_re)

    @override
    def queue_images(self) -> Literal[CoverArtProvider.QueueState.FINISHED]:
        plugin_config = self.api.plugin_config

        # find thumbnail
        regex = plugin_config['cover_thumbnail_regex']
        thumbnails = sorted(self._search_images(regex), key=_cover_order)

        # find original
        regex = plugin_config['cover_unprocessed_regex']
        unprocessed = sorted(self._search_images(regex), key=_cover_order)

        for image in thumbnails:
            image.can_be_processed = False  # no re-processing
            if unprocessed:
                unprocessed_image = unprocessed[0]
                # do not output the image referenced as our unprocessed master
                unprocessed = unprocessed[1:]
            else:
                # if none found, we're the unprocessed data ourselves
                unprocessed_image = image
            if unprocessed_image.url:
                cast(
                    '_CoverArtImageWithUnprocessed', image
                )._uc_unprocessed_filepath = unprocessed_image.url.toLocalFile()
                self.queue_put(image)

        for image in unprocessed:
            self.queue_put(image)

        return CoverArtProvider.QueueState.FINISHED


@monkey.patch(CoverArtImageProcessing, CoverArtImageProcessing._run_image_processors)
def _monkey_CoverArtImageProcessing_run_image_processors(
    wrapped: Callable[[CoverArtImageProcessing, CoverArtImage, bytes, ImageInfo], None],
    self: CoverArtImageProcessing,
    coverartimage: CoverArtImage,
    initial_data: bytes,
    image_info: ImageInfo,
) -> None:
    """Add unprocessed data if different from processed data."""
    # First call wrapped function...
    wrapped(self, coverartimage, initial_data, image_info)

    # ...then add data
    if _is_enabled() and (
        coverartimage.data != initial_data
        or (coverartimage.external_file_coverart and coverartimage.external_file_coverart.data != initial_data)
    ):
        cast('_CoverArtImageWithUnprocessed', coverartimage)._uc_unprocessed = initial_data


def _get_target_path(file: File, image: CoverArtImage, ext: str) -> Path:
    plugin_config = _api.plugin_config

    metadata = Metadata()
    metadata.copy(file.orig_metadata, copy_images=False)
    metadata.update(file.metadata)
    metadata['coverart_maintype'] = image.maintype
    metadata['coverart_comment'] = image.comment
    if image.is_front:
        metadata.add_unique('coverart_types', 'front')
    for cover_type in image.types:
        metadata.add_unique('coverart_types', cover_type)

    filename = scripttofilename.script_to_filename(plugin_config['cover_unprocessed_name'], metadata)
    return Path(file.filename).parent / (filename + ext)


def _existing_target_path(
    file: File,
    image: CoverArtImage,
    target_path: Path,
    *,
    unprocessed: bytes | None = None,
    check_path: Path | None = None,
    index: int = 1,
) -> Path | None:
    """Rename other files as long as name is free.

    Returns:
        The path if the data is already saved under a different name.
    """
    if not check_path:
        check_path = target_path

    if not check_path.exists():
        # saving/renaming required
        return None

    if not unprocessed:
        # remaining checks require data
        unprocessed = cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed

    if check_path.read_bytes() == unprocessed:
        # exists and same image -> no saving required, but rename
        return check_path

    new_path = target_path.with_stem(f'{target_path.stem}_{index:d}')

    result = _existing_target_path(
        file, image, target_path, unprocessed=unprocessed, check_path=new_path, index=index + 1
    )
    _rename_image(file, check_path, new_path)

    return result


def _rename_image(file: File, filepath: Path, new_filepath: Path) -> None:
    """Rename image file and update references.

    Raises:
        ValueError: If new filepath is not in the same folder as the old filepath.
    """
    for image in (img for md in (file.metadata, file.orig_metadata) for img in md.images._images):
        for img in (image, image.external_file_coverart):
            if img and img.url and filepath.samefile(img.url.toLocalFile()):
                img.url = QtCore.QUrl.fromLocalFile(str(new_filepath))

        if cast('_CoverArtImageWithUnprocessed', image)._uc_has_unprocessed_filepath and filepath.samefile(
            cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed_filepath
        ):
            # update unprocessed path in main file
            cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed_reset()
            cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed_filepath = str(new_filepath)
    if new_filepath.parent != filepath.parent:
        # expected to live in same folder
        raise ValueError(f"Files {filepath} and {new_filepath} are expected to be in the same folder.")
    _api.logger.debug_if(DebugOpt.COVERART, "Renaming to %r: %r", new_filepath.name, filepath)
    filepath.rename(new_filepath)


def _save_or_rename_unprocessed_cover(api: PluginApi, file: File) -> None:
    """Save and rename unprocessed cover."""
    if not _is_enabled():
        return

    # rename any associated images
    for image in file.metadata.images._images:
        unprocessed_path = Path(cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed_filepath)
        # unprocessed_path could be either image.url or the stored unprocessed path
        if not image.can_be_processed and image.url and unprocessed_path.samefile(image.url.toLocalFile()):
            # filter out thumbnails without companion file
            continue
        # file already exists, but may require a rename
        target_path = _get_target_path(file, image, unprocessed_path.suffix)
        if not unprocessed_path.samefile(target_path):
            # path was updated
            source_path = _existing_target_path(file, image, target_path)
            if source_path:
                unprocessed_path = source_path
            api.logger.debug("Cover %r using existing file: %r", target_path, unprocessed_path)
            _rename_image(file, unprocessed_path, target_path)

    # now save front image if not already existing

    image = file._images.get_front_image()
    if not image or isinstance(image, (LocalFileCoverArtImage, TagCoverArtImage)):
        # already exists or no file, i.e. from tag only
        return
    if not hasattr(image, '_uc_unprocessed_data'):
        return

    unprocessed = cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed
    if not unprocessed:
        return
    info = identify(unprocessed)
    extension = info.format_info.extension if info.format_info else ''

    target_path = _get_target_path(file, image, extension)
    source_path = _existing_target_path(file, image, target_path, unprocessed=unprocessed)
    if source_path:
        _rename_image(file, source_path, target_path)
    else:
        target_path.write_bytes(unprocessed)

    # now there is a file, so replace
    cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed_reset()
    cast('_CoverArtImageWithUnprocessed', image)._uc_unprocessed_filepath = str(target_path)


def enable(api: PluginApi) -> None:
    """Enable plugin."""
    global _api

    _api = api
    api.plugin_config.register_option(
        'cover_thumbnail_regex',
        r'^folder(\**)\.jpg$',
        api.tr('options.cover_thumbnail_regex', "Regex for finding processed thumbnail image"),
        in_profile=True,
    )
    api.plugin_config.register_option(
        'cover_unprocessed_regex',
        r'^(?!folder)(?:.*[_-])?(.*)?\.jpg$',
        api.tr('options.cover_unprocessed_regex', "Regex for finding unprocessed cover image"),
        in_profile=True,
    )
    api.plugin_config.register_option(
        'cover_unprocessed_name',
        default='$if2(%albumartistsort%,%albumartist%)_$if2(%albumsort%,%album%)_$if2($title(%coverart_maintype%),Cover)',
        title=api.tr('options.cover_unprocessed_name', "Expression to evaluate for saving unprocessed cover name"),
        in_profile=True,
    )

    api.register_cover_art_provider(UnprocessedCoverArtProvider)
    api.register_file_post_save_processor(_save_or_rename_unprocessed_cover)
    _add_infodialog_column()


def disable() -> None:
    """Disable plugin."""
    global _api

    _remove_infodialog_column()
    monkey.unpatch_module(__name__)

    del _api

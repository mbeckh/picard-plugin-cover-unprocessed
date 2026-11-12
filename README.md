# Unprocessed Covers

A plugin for [MusicBrainz Picard](https://picard.musicbrainz.org) to manage already processed covers and their unprocessed counterparts.

## What it Does

The plugin adds a cover art provider which can search for both already processed images (i.e. thumbnails) and unprocessed files while preferring the former.

The plugin also adds a column to the artwork tab in the info dialog to show the unprocessed image (if found).

The unprocessed image is saved alongside the music files using a configurable name and renamed automatically.

## Usage

The typical use case is to save the processed covers using the functionality of Picard to save them to a file such as `folder.jpg`.

## License

The code is released under the Apache License Version 2.0. Please see [LICENSE](LICENSE) for details and [NOTICE](NOTICE) for the required information when using picard-plugin-cover-unprocessed in your own work.
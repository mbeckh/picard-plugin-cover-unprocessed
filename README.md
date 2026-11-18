# Unprocessed Covers

![Latest Version](https://img.shields.io/github/v/tag/mbeckh/picard-plugin-cover-unprocessed?sort=semver&filter=v*&style=flat-square&label=latest)
![Supports](https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmbeckh%2Fpicard-plugin-cover-unprocessed%2Frefs%2Fheads%2Fmain%2Fpyproject.toml&search=dependencies%5Cs*%3D%5Cs*%5C%5B%5B%5E%5D%5D*%22picard%5B%5E%22%5D*(%3E%3D.*%3F)%5B%2C%22%5D&replace=%241&flags=s&style=flat-square&label=picard&color=orange)
![Tested with](https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmbeckh%2Fpicard-plugin-cover-unprocessed%2Frefs%2Fheads%2Fmain%2Fpyproject.toml&search=dependencies%5Cs*%3D%5Cs*%5C%5B%5B%5E%5D%5D*%22picard%5B%5E%22%5D*(%3C%3D.*%3F)%5B%2C%22%5D&replace=%241&flags=s&style=flat-square&label=tested+with&color=green)

A plugin for [MusicBrainz Picard](https://picard.musicbrainz.org) to manage
already processed covers and their unprocessed counterparts.

## What it Does

The plugin adds a cover art provider which can search for both already processed
images (i.e. thumbnails) and unprocessed files while preferring the former.

The plugin also adds a column to the artwork tab in the info dialog to show the
unprocessed image (if found).

The unprocessed image is saved alongside the music files using a configurable
name and renamed automatically.

## Unsupported Modifications of Picard

> [!IMPORTANT]
> This plugin requires the
> [Monkey Plugin](https://github.com/mbeckh/picard-plugin-monkey/) as a
> prerequisite. Please install this plugin first.

This plugin modifies Picard _way beyond_ the level that was intended by the
implementers of the official API. It relies heavily on internal and private
implementation details and monkey patches its way across the Picard code base to
achieve its goals.

> [!WARNING]
> **Even a minor update of Picard can break this plugin** until I'm able to
> supply an updated version. The plugin is typically tested with the latest
> version of Picard only.

## Usage

The typical use case is to save the processed covers using the functionality of
Picard to save them to a file such as `folder.jpg`.

## License

The code is released under the Apache License Version 2.0. Please see
[LICENSE](LICENSE) for details and [NOTICE](NOTICE) for the required information
when using picard-plugin-cover-unprocessed in your own work.

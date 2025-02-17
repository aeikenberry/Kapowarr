#-*- coding: utf-8 -*-

"""
The post-download processing (a.k.a. post-processing or PP) of downloads
"""

from __future__ import annotations

import logging
from os.path import basename, exists, join
from time import time
from typing import TYPE_CHECKING

from backend.conversion import mass_convert
from backend.converters import extract_files_from_folder
from backend.db import get_db
from backend.download_torrent_clients import TorrentDownload
from backend.files import copy_directory, delete_file_folder, rename_file
from backend.naming import mass_rename
from backend.settings import Settings
from backend.volumes import Volume, scan_files

if TYPE_CHECKING:
	from backend.download_general import Download

class PostProcessingActions:
	@staticmethod
	def remove_from_queue(download: Download) -> None:
		"Delete the download from the queue in the database"
		get_db().execute(
			"DELETE FROM download_queue WHERE id = ?",
			(download.id,)
		)
		return

	@staticmethod
	def add_to_history(download: Download) -> None:
		"Add the download to history in the database"
		get_db().execute(
			"""
			INSERT INTO download_history(original_link, title, downloaded_at)
			VALUES (?,?,?);
			""",
			(download.page_link, download.title, round(time()))
		)
		return

	@staticmethod
	def move_file(download: Download) -> None:
		"Move file from download folder to final destination"
		if exists(download.file):
			folder = Volume(download.volume_id)['folder']
			file_dest = join(folder, basename(download.file))
			logging.debug(
				f'Moving download to final destination: {download}, Dest: {file_dest}'
			)

			if exists(file_dest):
				logging.warning(
					f'The file/folder {file_dest} already exists; replacing with downloaded file'
				)
				delete_file_folder(file_dest)

			rename_file(download.file, file_dest)
			download.file = file_dest
		return

	@staticmethod
	def delete_file(download: Download) -> None:
		"Delete file from download folder"
		delete_file_folder(download.file)
		return

	@staticmethod
	def add_file_to_database(download: Download) -> None:
		"Register file in database and match to a volume/issue"
		scan_files(download.volume_id)
		return

	@staticmethod
	def convert_file(download: Download) -> None:
		"Convert a file into a different format based on settings"
		if not Settings()['convert']:
			return

		if isinstance(download, TorrentDownload):
			mass_convert(
				download.volume_id,
				download.issue_id,
				files=download.resulting_files
			)
		else:
			mass_convert(
				download.volume_id,
				download.issue_id,
				files=[download.file]
			)
		return

	@staticmethod
	def move_file_torrent(download: TorrentDownload) -> None:
		"""Move file downloaded using torrent from download folder to
		final destination"""
		PPA.move_file(download)

		download.resulting_files = extract_files_from_folder(
			download.file,
			download.volume_id
		)

		scan_files(download.volume_id)

		rename_files = Settings()['rename_downloaded_files']

		if rename_files and download.resulting_files:
			mass_rename(
				download.volume_id,
				filepath_filter=download.resulting_files
			)

		return

	@staticmethod
	def copy_file_torrent(download: TorrentDownload) -> None:
		"""Copy downloaded files to dest. Change download.file to copy.
		Change back using `PPA.reset_file_link()`.
		"""
		download.original_file = download.file
		if exists(download.file):
			folder = Volume(download.volume_id)['folder']
			file_dest = join(folder, basename(download.file))
			logging.debug(
				f'Copying download to final destination: {download}, Dest: {file_dest}'
			)

			if exists(file_dest):
				logging.warning(
					f'The file/folder {file_dest} already exists; replacing with downloaded file'
				)
				delete_file_folder(file_dest)

			copy_directory(download.file, file_dest)
			download.file = file_dest

			download.resulting_files = extract_files_from_folder(
				download.file,
				download.volume_id
			)

			scan_files(download.volume_id)

			rename_files = Settings()['rename_downloaded_files']

			if rename_files and download.resulting_files:
				mass_rename(
					download.volume_id,
					filepath_filter=download.resulting_files
				)
		return

	@staticmethod
	def reset_file_link(download: TorrentDownload) -> None:
		"Set download.file back to original folder from the copied folder"
		download.file = download.original_file
		return

PPA = PostProcessingActions
"""Rename of PostProcessingActions to make local code less cluttered.
Advised to use the name `PostProcessingActions` outside of this file."""

class PostProcesser:
	actions_success = [
		PPA.remove_from_queue,
		PPA.add_to_history,
		PPA.move_file,
		PPA.add_file_to_database,
		PPA.convert_file,
		PPA.add_file_to_database
	]

	actions_canceled = [
		PPA.delete_file,
		PPA.remove_from_queue
	]

	actions_shutdown = [
		PPA.delete_file
	]

	actions_failed = [
		PPA.remove_from_queue,
		PPA.add_to_history,
		PPA.delete_file
	]

	@staticmethod
	def _run_actions(actions: list, download) -> None:
		for action in actions:
			action(download)
		return

	@classmethod
	def success(cls, download) -> None:
		logging.info(f'Postprocessing of successful download: {download.id}')
		cls._run_actions(cls.actions_success, download)
		return

	@classmethod
	def canceled(cls, download) -> None:
		logging.info(f'Postprocessing of canceled download: {download.id}')
		cls._run_actions(cls.actions_canceled, download)
		return

	@classmethod
	def shutdown(cls, download) -> None:
		logging.info(f'Postprocessing of shut down download: {download.id}')
		cls._run_actions(cls.actions_shutdown, download)
		return

	@classmethod
	def failed(cls, download) -> None:
		logging.info(f'Postprocessing of failed download: {download.id}')
		cls._run_actions(cls.actions_failed, download)
		return

class PostProcesserTorrentsComplete(PostProcesser):
	actions_success = [
		PPA.remove_from_queue,
		PPA.add_to_history,
		PPA.move_file_torrent,
		PPA.convert_file,
		PPA.add_file_to_database
	]

class PostProcesserTorrentsCopy(PostProcesser):
	actions_success = [
		PPA.remove_from_queue,
		PPA.delete_file
	]
	
	actions_seeding = [
		PPA.add_to_history,
		PPA.copy_file_torrent,
		PPA.convert_file,
		PPA.add_file_to_database,
		PPA.reset_file_link
	]
	
	@classmethod
	def seeding(cls, download) -> None:
		logging.info(f'Postprocessing of seeding download: {download.id}')
		cls._run_actions(cls.actions_seeding, download)
		return

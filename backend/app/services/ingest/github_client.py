from pathlib import Path
from urllib.parse import urlparse
import os
import subprocess
import requests
import logging
import shutil
import stat

from app.services.ingest.ingest_db_ops import IngestDbOps

logger = logging.getLogger(__name__)


class GithubClient(IngestDbOps):
    def __init__(self, github_url: str) -> None:
        self.github_url = github_url
        self.target_dir = Path("./_repo").resolve()
        self.absolute_path = Path(self.target_dir).resolve()

    def _fetch_repo_details(self) -> dict:
        repo_path = urlparse(self.github_url).path.strip("/")
        owner, repo = repo_path.split("/")[:2]
        repo = repo.removesuffix(".git")

        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        logger.info("[GITHUB-CLIENT] FETCHING THE REPO DETAILS AT %s", api_url)

        response = requests.get(api_url)
        response.raise_for_status()

        return response.json()

    async def _fetch_github_repo(self) -> bool:
        try:
            does_exist = False
            result = None
            data = await self.get_repo_detail(github_url=self.github_url)

            if data is not None:
                logger.info(
                    "[GITHUB-CLIENT] REPO ALREADY EXIST, SETTING THE ID FROM DB"
                )
                self.repo_id = data["repo_id"]
                self.repo_name = data["repo_full_name"]
                does_exist = True
            else:
                does_exist = False
                logger.info("[GITHUB-CLIENT] FETCHING THE REPO DETAILS")
                details = self._fetch_repo_details()

                await self.save_repo_details(
                    github_url=self.github_url, details=details
                )
            if os.path.exists(self.target_dir) and os.listdir(self.target_dir):
                raise FileExistsError("TARGET DIR IS NOT EMPTY")

            process = ["git", "clone", self.github_url, str(self.target_dir)]

            logger.info("[GITHUB-CLIENT] CLONING THE GIT REPO...")
            subprocess.run(process, capture_output=True, text=True, check=True)

            logger.info("[GITHUB-CLIENT] CLONING COMPLETE")

            return does_exist

        except FileExistsError as e:
            logger.exception("[GITHUB-CLIENT] TARGET DIRECTORY IS NOT EMPTY: %s", e)
            raise

        except IndexError as e:
            logger.exception(
                "[GITHUB-CLIENT] THE GITHUB URL PROVIDED IS PROBALY NOT GOOD, %s, CAUSING A ERROR WHILE FETCHING DETAILS",
                self.github_url,
            )
            raise

        except requests.exceptions.HTTPError as e:
            logger.exception(
                "[GITHUB-CLIENT] HTTP ERROR WHILE FETCHING REPO DETAILS, ERROR %s",
                e,
            )
            raise

        except subprocess.CalledProcessError as e:
            logger.exception(
                "[GITHUB-CLIENT] COMMAND FAILED EXIT CODE: %s, MESSAGE: %s",
                e.returncode,
                e.stderr.strip(),
            )
            raise

        except Exception as e:
            logger.exception("[GITHUB-CLIENT] UNDEFINED ERROR: %s", e)
            raise

    def _remove_github_repo(self) -> None:
        if not self.absolute_path.exists():
            return

        def remove_readonly(func, path, exec_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        try:
            shutil.rmtree(self.absolute_path, onexc=remove_readonly)
            logger.info("[GITHUB-CLIENT] REPO DELETED: %s", self.absolute_path)
        except Exception as e:
            logger.exception(
                "[GITHUB-CLIENT] FAILED TO DELETE REPO at %s: %s",
                self.absolute_path,
                e,
            )
            raise

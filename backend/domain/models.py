from __future__ import annotations

from pydantic import BaseModel, Field


class PreviewRequest(BaseModel):
    source_url: str = Field(alias="sourceUrl")
    scope: str = "auto"


class PreviewItem(BaseModel):
    index: int | None = None
    id: str | None = None
    title: str
    duration: int | None = None


class PreviewResponse(BaseModel):
    kind: str
    source_url: str = Field(alias="sourceUrl")
    id: str | None = None
    title: str
    channel: str | None = None
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")
    thumbnail_source_url: str | None = Field(default=None, exclude=True)
    duration: int | None = None
    upload_date: str | None = Field(default=None, alias="uploadDate")
    view_count: int | None = Field(default=None, alias="viewCount")
    item_count: int | None = Field(default=None, alias="itemCount")
    scope_options: list[str] = Field(alias="scopeOptions")
    items: list[PreviewItem] = []


class JobCreateRequest(BaseModel):
    source_url: str = Field(alias="sourceUrl")
    scope: str = "auto"
    preset: str
    quality: str
    target_directory: str | None = Field(default=None, alias="targetDirectory")
    conflict_policy: str = Field(default="skip", alias="conflictPolicy")


class SettingsPatch(BaseModel):
    default_download_dir: str | None = Field(default=None, alias="defaultDownloadDir")
    default_preset: str | None = Field(default=None, alias="defaultPreset")
    default_quality: str | None = Field(default=None, alias="defaultQuality")
    concurrent_downloads: int | None = Field(default=None, alias="concurrentDownloads")
    conflict_policy: str | None = Field(default=None, alias="conflictPolicy")
    theme: str | None = None
    language: str | None = None
    open_folder_on_complete: bool | None = Field(default=None, alias="openFolderOnComplete")

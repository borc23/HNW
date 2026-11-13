"use server";

import { ApiError, api, type Job } from "@/lib/api";

export type ImportState =
  | { kind: "idle" }
  | { kind: "error"; message: string }
  | { kind: "queued"; jobId: string };

const MAX_URL_LENGTH = 2048;

export async function startImport(_prev: ImportState, form: FormData): Promise<ImportState> {
  const url = String(form.get("url") ?? "").trim();
  if (!url) return { kind: "error", message: "Paste a link to a listing first." };
  if (url.length > MAX_URL_LENGTH) return { kind: "error", message: "That link is too long." };
  try {
    const { job_id } = await api.importListing(url);
    return { kind: "queued", jobId: job_id };
  } catch (error) {
    const unsupported = error instanceof ApiError && error.status === 422;
    return { kind: "error", message: unsupported ? unsupportedMessage(url) : messageOf(error) };
  }
}

function unsupportedMessage(url: string): string {
  const host = URL.canParse(url) ? new URL(url).hostname.replace(/^www\./, "") : "that site";
  return `We can't read links from ${host} yet. Paste a listing link from huurwoningen.nl.`;
}

export type JobCheck = { ok: true; job: Job } | { ok: false; message: string };

export async function checkJob(jobId: string): Promise<JobCheck> {
  try {
    return { ok: true, job: await api.getJob(jobId) };
  } catch (error) {
    return { ok: false, message: messageOf(error) };
  }
}

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

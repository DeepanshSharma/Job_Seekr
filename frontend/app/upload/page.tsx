"use client";

import { useState } from "react";
import { supabase } from "../../lib/supabase";

const ROLE_TYPES = ["DA", "BA", "AI"] as const;
type RoleType = (typeof ROLE_TYPES)[number];

const ROLE_LABELS: Record<RoleType, string> = {
  DA: "Data Analyst",
  BA: "Business Analyst",
  AI: "Data Scientist / AI Engineer",
};

export default function UploadPage() {
  const [roleType, setRoleType] = useState<RoleType>("DA");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const text = await file.text();
    setContent(text);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) {
      setStatus("error");
      setMessage("Resume content is empty. Paste text or upload a file.");
      return;
    }

    setStatus("uploading");
    setMessage("");

    const { error } = await supabase.from("resumes").insert({
      user_id: "deepansh",
      role_type: roleType,
      content: content.trim(),
      file_name: fileName || `${roleType}_resume`,
    });

    if (error) {
      setStatus("error");
      setMessage(`Upload failed: ${error.message}`);
    } else {
      setStatus("success");
      setMessage(`${ROLE_LABELS[roleType]} resume uploaded successfully.`);
      setContent("");
      setFileName("");
    }
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Upload Resume</h1>
        <p className="text-sm text-gray-500 mt-1">
          Upload a resume variant to Supabase. The pipeline uses these to route jobs.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Role type selector */}
        <div className="space-y-2">
          <label className="text-sm text-gray-400">Resume Type</label>
          <div className="flex gap-3">
            {ROLE_TYPES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRoleType(r)}
                className={`px-4 py-2 rounded text-sm font-semibold border transition-colors ${
                  roleType === r
                    ? "bg-indigo-600 border-indigo-500 text-white"
                    : "border-gray-700 text-gray-400 hover:border-gray-500"
                }`}
              >
                {r} — {ROLE_LABELS[r]}
              </button>
            ))}
          </div>
        </div>

        {/* File upload */}
        <div className="space-y-2">
          <label className="text-sm text-gray-400">Upload File (optional — reads as plain text)</label>
          <input
            type="file"
            accept=".txt,.md,.pdf"
            onChange={handleFileChange}
            className="block w-full text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 cursor-pointer"
          />
          {fileName && <p className="text-xs text-gray-600">Loaded: {fileName}</p>}
        </div>

        {/* Manual text input */}
        <div className="space-y-2">
          <label className="text-sm text-gray-400">Resume Content (plain text)</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={14}
            placeholder="Paste your resume text here, or upload a file above…"
            className="w-full rounded border border-gray-700 bg-gray-900 text-gray-200 text-sm px-4 py-3 resize-none focus:outline-none focus:border-indigo-500"
          />
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={status === "uploading"}
          className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 rounded font-semibold text-sm transition-colors disabled:opacity-40"
        >
          {status === "uploading" ? "Uploading…" : `Upload ${roleType} Resume`}
        </button>

        {/* Status message */}
        {status === "success" && (
          <p className="text-sm text-green-400 border border-green-800 bg-green-950 rounded px-4 py-2">
            {message}
          </p>
        )}
        {status === "error" && (
          <p className="text-sm text-red-400 border border-red-800 bg-red-950 rounded px-4 py-2">
            {message}
          </p>
        )}
      </form>
    </div>
  );
}

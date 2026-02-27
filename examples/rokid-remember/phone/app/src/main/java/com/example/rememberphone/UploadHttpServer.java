package com.example.rememberphone;

import android.Manifest;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import androidx.core.content.ContextCompat;

import fi.iki.elonen.NanoHTTPD;
import fi.iki.elonen.NanoHTTPD.IHTTPSession;
import fi.iki.elonen.NanoHTTPD.Response;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

class UploadHttpServer extends NanoHTTPD {
    private static final int IO_BUFFER_SIZE = 1024 * 1024;
    private static final Set<String> ALLOWED_EXTENSIONS = Set.of(".mp4", ".m4a");
    private static final String MODE_VIDEO = "video";
    private static final String MODE_AUDIO = "audio";
    private static final String RELATIVE_DOWNLOAD_PATH = Environment.DIRECTORY_DOWNLOADS + "/RokidRemember/";

    private final Context appContext;

    UploadHttpServer(Context context, int port) {
        super(port);
        this.appContext = context.getApplicationContext();
    }

    @Override
    public Response serve(IHTTPSession session) {
        String uri = session.getUri();
        Method method = session.getMethod();

        if ("/health".equals(uri)) {
            if (Method.GET != method) {
                return jsonResponse(Response.Status.METHOD_NOT_ALLOWED, detail("method not allowed"));
            }
            return jsonResponse(Response.Status.OK, "{\"status\":\"ok\"}");
        }

        if ("/upload".equals(uri)) {
            if (Method.POST != method) {
                return jsonResponse(Response.Status.METHOD_NOT_ALLOWED, detail("method not allowed"));
            }
            return handleUpload(session);
        }

        return jsonResponse(Response.Status.NOT_FOUND, detail("not found"));
    }

    private Response handleUpload(IHTTPSession session) {
        String contentType = session.getHeaders().get("content-type");
        if (contentType == null
                || !contentType.toLowerCase(Locale.US).contains("multipart/form-data")) {
            return jsonResponse(
                    Response.Status.BAD_REQUEST,
                    detail("content-type must be multipart/form-data")
            );
        }

        Map<String, String> files = new HashMap<>();
        try {
            session.parseBody(files);
        } catch (Exception e) {
            return jsonResponse(Response.Status.BAD_REQUEST, detail("invalid multipart body"));
        }

        Map<String, List<String>> params = session.getParameters();
        String mode = normalizedMode(firstValue(params, "mode"));
        String defaultExt = defaultExtension(mode);
        if (defaultExt == null) {
            return jsonResponse(Response.Status.BAD_REQUEST, detail("mode must be 'video' or 'audio'"));
        }

        Long startUnix = parseLong(firstValue(params, "start_unix"));
        Long endUnix = parseLong(firstValue(params, "end_unix"));
        if (startUnix == null || endUnix == null) {
            return jsonResponse(
                    Response.Status.BAD_REQUEST,
                    detail("start_unix and end_unix must be integers")
            );
        }
        if (endUnix <= startUnix) {
            return jsonResponse(
                    Response.Status.BAD_REQUEST,
                    detail("end_unix must be greater than start_unix")
            );
        }

        String filePath = files.get("file");
        if (filePath == null) {
            return jsonResponse(Response.Status.BAD_REQUEST, detail("file is required"));
        }
        File uploadedPart = new File(filePath);
        if (!uploadedPart.exists()) {
            return jsonResponse(Response.Status.BAD_REQUEST, detail("uploaded file is missing"));
        }

        String incomingFilename = firstValue(params, "file");
        String incomingExt = extensionOf(incomingFilename);
        String ext = ALLOWED_EXTENSIONS.contains(incomingExt) ? incomingExt : defaultExt;
        String targetFilename = startUnix + "-" + endUnix + ext;

        try {
            saveUploadedFile(uploadedPart, targetFilename, mimeTypeFor(ext));
        } catch (IOException e) {
            return jsonResponse(
                    Response.Status.INTERNAL_ERROR,
                    detail("failed to save upload: " + (e.getMessage() == null ? "unknown error" : e.getMessage()))
            );
        } finally {
            // Body parser temp files live in app cache; clean them once copied.
            //noinspection ResultOfMethodCallIgnored
            uploadedPart.delete();
        }

        return jsonResponse(
                Response.Status.OK,
                "{\"status\":\"ok\",\"filename\":\"" + escapeJson(targetFilename) + "\"}"
        );
    }

    private void saveUploadedFile(File source, String filename, String mimeType) throws IOException {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            saveViaMediaStore(source, filename, mimeType);
            return;
        }
        saveLegacyExternalFile(source, filename);
    }

    private void saveViaMediaStore(File source, String filename, String mimeType) throws IOException {
        ContentResolver resolver = appContext.getContentResolver();
        Uri collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        removeExistingMediaStoreEntries(resolver, collection, filename);

        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, filename);
        values.put(MediaStore.MediaColumns.MIME_TYPE, mimeType);
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, RELATIVE_DOWNLOAD_PATH);
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);

        Uri targetUri = resolver.insert(collection, values);
        if (targetUri == null) {
            throw new IOException("unable to create output file");
        }

        try (InputStream input = new FileInputStream(source);
             OutputStream output = resolver.openOutputStream(targetUri, "w")) {
            if (output == null) {
                throw new IOException("unable to open output stream");
            }
            copy(input, output);
        } catch (IOException e) {
            resolver.delete(targetUri, null, null);
            throw e;
        }

        ContentValues completeValues = new ContentValues();
        completeValues.put(MediaStore.MediaColumns.IS_PENDING, 0);
        resolver.update(targetUri, completeValues, null, null);
    }

    private void removeExistingMediaStoreEntries(
            ContentResolver resolver,
            Uri collection,
            String filename
    ) {
        String selection = MediaStore.MediaColumns.DISPLAY_NAME + " = ? AND "
                + MediaStore.MediaColumns.RELATIVE_PATH + " = ?";
        String[] args = new String[]{filename, RELATIVE_DOWNLOAD_PATH};
        try (Cursor cursor = resolver.query(
                collection,
                new String[]{MediaStore.MediaColumns._ID},
                selection,
                args,
                null
        )) {
            if (cursor == null) {
                return;
            }

            int idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID);
            while (cursor.moveToNext()) {
                long id = cursor.getLong(idIndex);
                Uri uri = ContentUris.withAppendedId(collection, id);
                resolver.delete(uri, null, null);
            }
        }
    }

    @SuppressWarnings("deprecation")
    private void saveLegacyExternalFile(File source, String filename) throws IOException {
        if (ContextCompat.checkSelfPermission(
                appContext,
                Manifest.permission.WRITE_EXTERNAL_STORAGE
        ) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            throw new IOException("WRITE_EXTERNAL_STORAGE permission is required on Android 9 and below");
        }

        File downloadsDir = Environment.getExternalStoragePublicDirectory(
                Environment.DIRECTORY_DOWNLOADS
        );
        File targetDir = new File(downloadsDir, "RokidRemember");
        if (!targetDir.exists() && !targetDir.mkdirs()) {
            throw new IOException("unable to create destination directory");
        }

        File target = new File(targetDir, filename);
        File tempTarget = new File(targetDir, filename + ".part");
        try (InputStream input = new FileInputStream(source);
             OutputStream output = new FileOutputStream(tempTarget)) {
            copy(input, output);
        }

        if (target.exists() && !target.delete()) {
            throw new IOException("unable to overwrite existing file");
        }
        if (!tempTarget.renameTo(target)) {
            throw new IOException("unable to finalize file");
        }
    }

    private static void copy(InputStream input, OutputStream output) throws IOException {
        byte[] buffer = new byte[IO_BUFFER_SIZE];
        int read;
        while ((read = input.read(buffer)) != -1) {
            output.write(buffer, 0, read);
        }
        output.flush();
    }

    private static String firstValue(Map<String, List<String>> params, String key) {
        List<String> values = params.get(key);
        if (values == null || values.isEmpty()) {
            return null;
        }
        return values.get(0);
    }

    private static String normalizedMode(String rawMode) {
        if (rawMode == null) {
            return "";
        }
        return rawMode.trim().toLowerCase(Locale.US);
    }

    private static String defaultExtension(String mode) {
        if (MODE_VIDEO.equals(mode)) {
            return ".mp4";
        }
        if (MODE_AUDIO.equals(mode)) {
            return ".m4a";
        }
        return null;
    }

    private static Long parseLong(String value) {
        if (value == null) {
            return null;
        }
        try {
            return Long.parseLong(value.trim());
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static String extensionOf(String filename) {
        if (filename == null || filename.isBlank()) {
            return "";
        }
        int index = filename.lastIndexOf('.');
        if (index < 0 || index == filename.length() - 1) {
            return "";
        }
        return filename.substring(index).toLowerCase(Locale.US);
    }

    private static String mimeTypeFor(String ext) {
        if (".mp4".equals(ext)) {
            return "video/mp4";
        }
        if (".m4a".equals(ext)) {
            return "audio/mp4";
        }
        return "application/octet-stream";
    }

    private static String escapeJson(String value) {
        return value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"");
    }

    private static String detail(String message) {
        return "{\"detail\":\"" + escapeJson(message) + "\"}";
    }

    private static Response jsonResponse(Response.Status status, String body) {
        return NanoHTTPD.newFixedLengthResponse(status, "application/json", body);
    }
}

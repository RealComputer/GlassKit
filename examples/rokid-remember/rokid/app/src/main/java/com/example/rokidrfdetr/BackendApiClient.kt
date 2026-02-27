package com.example.rokidrfdetr

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

object BackendApiClient {
    private const val TAG = "BackendApiClient"

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    suspend fun checkHealth(baseUrl: String): Boolean = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(buildUrl(baseUrl, "health"))
            .get()
            .build()

        return@withContext try {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    return@use false
                }
                val body = response.body?.string().orEmpty()
                JSONObject(body).optString("status") == "ok"
            }
        } catch (t: Throwable) {
            Log.w(TAG, "Health check failed", t)
            false
        }
    }

    suspend fun uploadSegment(
        baseUrl: String,
        file: File,
        mode: RecorderMode,
        startUnix: Long,
        endUnix: Long
    ): Boolean = withContext(Dispatchers.IO) {
        val mediaType = when (mode) {
            RecorderMode.VIDEO -> "video/mp4"
            RecorderMode.AUDIO -> "audio/mp4"
        }.toMediaType()

        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("mode", mode.wireValue)
            .addFormDataPart("start_unix", startUnix.toString())
            .addFormDataPart("end_unix", endUnix.toString())
            .addFormDataPart("file", file.name, file.asRequestBody(mediaType))
            .build()

        val request = Request.Builder()
            .url(buildUrl(baseUrl, "upload"))
            .post(body)
            .build()

        return@withContext try {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Log.w(TAG, "Upload failed: HTTP ${response.code}")
                    return@use false
                }
                val raw = response.body?.string().orEmpty()
                if (raw.isBlank()) {
                    true
                } else {
                    JSONObject(raw).optString("status") == "ok"
                }
            }
        } catch (t: Throwable) {
            Log.w(TAG, "Upload failed for ${file.name}", t)
            false
        }
    }

    private fun buildUrl(baseUrl: String, path: String): String {
        val normalizedBase = baseUrl.trim().trimEnd('/')
        return "$normalizedBase/$path"
    }
}

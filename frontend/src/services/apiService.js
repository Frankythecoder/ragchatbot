const BACKEND_URL = "http://localhost:8000";

class ApiService {
  /**
   * Register a new user.
   */
  async register(username, email, password) {
    try {
      const res = await fetch(`${BACKEND_URL}/auth/register/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        return { success: false, message: data.detail || "Registration failed" };
      }
      return { success: true, message: data.message || "Account created successfully" };
    } catch (error) {
      return { success: false, message: `Could not reach backend. ${error.message}` };
    }
  }

  /**
   * Login an existing user. Returns JWT tokens.
   */
  async login(email, password) {
    try {
      const res = await fetch(`${BACKEND_URL}/auth/login/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        return { success: false, message: data.detail || "Login failed" };
      }
      return {
        success: true,
        message: data.message || "Login successful",
        body: {
          access_token: data.access_token,
          refresh_token: data.refresh_token,
        },
      };
    } catch (error) {
      return { success: false, message: `Could not reach backend. ${error.message}` };
    }
  }

  /**
   * Logout — blacklists the refresh token on the backend.
   */
  async logout(refreshToken, accessToken) {
    try {
      await fetch(`${BACKEND_URL}/auth/logout/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      return { success: true };
    } catch (error) {
      return { success: false };
    }
  }

  /**
   * Get all chat threads for the authenticated user.
   */
  async getThreads(accessToken) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/threads/`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (error) {
      console.error("ApiService.getThreads error:", error);
      return [];
    }
  }

  /**
   * Create a new chat thread.
   */
  async createThread(accessToken) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/threads/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (error) {
      console.error("ApiService.createThread error:", error);
      return null;
    }
  }

  /**
   * Get a single thread with all its messages.
   */
  async getThread(threadId, accessToken) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/threads/${threadId}/`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (error) {
      console.error("ApiService.getThread error:", error);
      return null;
    }
  }

  /**
   * Rename a chat thread.
   */
  async renameThread(threadId, title, accessToken) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/threads/${threadId}/`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (error) {
      console.error("ApiService.renameThread error:", error);
      return null;
    }
  }

  /**
   * Delete a chat thread.
   */
  async deleteThread(threadId, accessToken) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/threads/${threadId}/`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      return res.ok || res.status === 204;
    } catch (error) {
      console.error("ApiService.deleteThread error:", error);
      return false;
    }
  }

  /**
   * Send a message to a thread. Returns AI response + token usage.
   */
  async sendMessage(threadId, message, accessToken, files = [], mode = "normal") {
    try {
      const res = await fetch(`${BACKEND_URL}/api/threads/${threadId}/chat/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ message, files: files || [], mode }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (error) {
      console.error("ApiService.sendMessage error:", error);
      return {
        message: `Could not reach the backend. Make sure the Django server is running.\n\nError: ${error.message}`,
        tokens: null,
        thread_title: null,
        sources: [],
      };
    }
  }

  async uploadDocument(filePath, accessToken) {
    const fs = require("node:fs");
    const path = require("node:path");
    const filename = path.basename(filePath);

    const fileBuffer = fs.readFileSync(filePath);
    const formData = new FormData();
    formData.append("file", new Blob([fileBuffer]), filename);

    try {
      const res = await fetch(`${BACKEND_URL}/api/upload-document/`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (error) {
      console.error("ApiService.uploadDocument error:", error);
      return { success: false, message: error.message };
    }
  }
}

module.exports = new ApiService();

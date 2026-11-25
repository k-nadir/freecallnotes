/* FreeCallNotes launcher: starts the bundled Python with the app.
 * Copyright (C) 2026 Nadir Khawaja
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include <windows.h>
#include <wchar.h>
int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR a, int n) {
    wchar_t dir[MAX_PATH], py[MAX_PATH], cmd[2 * MAX_PATH];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *s = wcsrchr(dir, L'\\'); if (s) *s = 0;
    swprintf(py, MAX_PATH, L"%ls\\python\\pythonw.exe", dir);
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"FreeCallNotes is missing some of its files.\n\nKeep FreeCallNotes.exe inside the FreeCallNotes folder, next to the \"python\" and \"callrec\" folders.", L"FreeCallNotes", MB_ICONWARNING);
        return 1;
    }
    swprintf(cmd, 2 * MAX_PATH, L"\"%ls\" -m callrec", py);
    STARTUPINFOW si = { sizeof si }; PROCESS_INFORMATION pi;
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"FreeCallNotes could not start. Try restarting your computer.", L"FreeCallNotes", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}

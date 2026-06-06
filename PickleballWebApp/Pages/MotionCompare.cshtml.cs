using System;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using PickleballWebApp.Models;
using PickleballWebApp.Services;

namespace PickleballWebApp.Pages
{
    [IgnoreAntiforgeryToken]
    public class MotionCompareModel : PageModel
    {
        private readonly UserDataService _userData;

        public MotionCompareModel(UserDataService userData)
        {
            _userData = userData;
        }

        public string? CurrentUsername => User.Identity?.IsAuthenticated == true
            ? User.Identity.Name
            : null;

        public void OnGet() { }

        // Called by JS after a session finishes to persist the result.
        public async Task<IActionResult> OnPostSaveSessionAsync()
        {
            if (User.Identity?.IsAuthenticated != true)
                return new JsonResult(new { ok = false, error = "unauthenticated" });

            SessionResult? session;
            try
            {
                session = await JsonSerializer.DeserializeAsync<SessionResult>(
                    Request.Body,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            }
            catch
            {
                return new JsonResult(new { ok = false, error = "invalid_json" });
            }

            if (session == null)
                return new JsonResult(new { ok = false, error = "empty_body" });

            session.Id = Guid.NewGuid().ToString("N");
            session.CreatedAt = DateTime.UtcNow;
            session.Username = User.Identity.Name ?? "unknown";

            _userData.SaveSession(session);
            return new JsonResult(new { ok = true, id = session.Id });
        }
    }
}

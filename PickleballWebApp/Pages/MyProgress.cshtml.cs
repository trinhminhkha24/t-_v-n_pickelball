using System.Collections.Generic;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using PickleballWebApp.Models;
using PickleballWebApp.Services;

namespace PickleballWebApp.Pages
{
    [Authorize]
    public class MyProgressModel : PageModel
    {
        private readonly UserDataService _userData;

        public MyProgressModel(UserDataService userData)
        {
            _userData = userData;
        }

        public UserStats Stats { get; private set; } = new();
        public List<SessionResult> RecentSessions { get; private set; } = new();
        public List<PageVisit> RecentVisits { get; private set; } = new();

        public void OnGet()
        {
            var username = User.Identity!.Name!;
            Stats = _userData.GetStats(username);
            RecentSessions = _userData.GetSessions(username, 20);
            RecentVisits = _userData.GetRecentVisits(username, 15);
        }
    }
}

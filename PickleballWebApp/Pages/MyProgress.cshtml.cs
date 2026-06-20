using System.Threading.Tasks;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using PickleballWebApp.Models;
using PickleballWebApp.Services;

namespace PickleballWebApp.Pages
{
    public class MyProgressModel : PageModel
    {
        private readonly UserDataService _userData;

        private static readonly Dictionary<string, int?> RangeMap = new(StringComparer.OrdinalIgnoreCase)
        {
            ["all"] = null,
            ["7d"] = 7,
            ["30d"] = 30,
            ["90d"] = 90
        };

        public MyProgressModel(UserDataService userData)
        {
            _userData = userData;
        }

        [BindProperty(SupportsGet = true)]
        public string Range { get; set; } = "30d";

        public UserStats Stats { get; private set; } = new();
        public List<SessionResult> RecentSessions { get; private set; } = new();
        public List<PageVisit> RecentVisits { get; private set; } = new();
        public List<SessionResult> VisibleSessions { get; private set; } = new();
        public List<PageVisit> VisibleVisits { get; private set; } = new();
        public UserStats DashboardStats { get; private set; } = new();
        public string RangeLabel { get; private set; } = "30 ngày";
        public int? RangeDays { get; private set; } = 30;
        public DateTime? RangeStartUtc { get; private set; }
        public bool IsAuthenticated { get; private set; }

        public async Task OnGetAsync()
        {
            IsAuthenticated = User.Identity?.IsAuthenticated == true;

            if (!IsAuthenticated)
            {
                Stats = new UserStats();
                DashboardStats = new UserStats();
                RecentSessions = new List<SessionResult>();
                RecentVisits = new List<PageVisit>();
                VisibleSessions = new List<SessionResult>();
                VisibleVisits = new List<PageVisit>();
                return;
            }

            var userName = User.Identity?.Name ?? string.Empty;
            Stats          = _userData.GetStats(userName);
            RecentSessions = _userData.GetSessions(userName, 20);
            RecentVisits   = _userData.GetRecentVisits(userName, 15);

            if (!RangeMap.TryGetValue(Range ?? string.Empty, out var days))
            {
                Range = "30d";
                days = 30;
            }

            RangeDays = days;
            RangeLabel = days switch
            {
                null => "Toàn bộ",
                7 => "7 ngày",
                30 => "30 ngày",
                90 => "90 ngày",
                _ => "30 ngày"
            };

            RangeStartUtc = days.HasValue ? DateTime.UtcNow.AddDays(-days.Value) : null;

            VisibleSessions = FilterSessions(RecentSessions, RangeStartUtc);
            VisibleVisits = FilterVisits(RecentVisits, RangeStartUtc);
            DashboardStats = BuildStats(VisibleSessions);
        }

        private static List<SessionResult> FilterSessions(List<SessionResult> sessions, DateTime? rangeStartUtc)
        {
            if (!rangeStartUtc.HasValue) return sessions;
            return sessions
                .Where(s => s.CreatedAt.ToUniversalTime() >= rangeStartUtc.Value)
                .ToList();
        }

        private static List<PageVisit> FilterVisits(List<PageVisit> visits, DateTime? rangeStartUtc)
        {
            if (!rangeStartUtc.HasValue) return visits;
            return visits
                .Where(v => v.VisitedAt.ToUniversalTime() >= rangeStartUtc.Value)
                .ToList();
        }

        private static UserStats BuildStats(List<SessionResult> sessions)
        {
            if (sessions.Count == 0)
                return new UserStats();

            var accuracies = sessions.Select(s => s.OverallAccuracy).ToList();
            return new UserStats
            {
                TotalSessions = sessions.Count,
                AverageAccuracy = Math.Round(accuracies.Average(), 1),
                BestAccuracy = Math.Round(accuracies.Max(), 1),
                LastSessionAt = sessions.Max(s => s.CreatedAt),
                RecentTrend = ComputeTrend(sessions)
            };
        }

        private static double ComputeTrend(List<SessionResult> sessions)
        {
            if (sessions.Count < 4) return 0;
            var sorted = sessions.OrderBy(s => s.CreatedAt).ToList();
            var half = sorted.Count / 2;
            var older = sorted.Take(half).Average(s => s.OverallAccuracy);
            var newer = sorted.Skip(half).Average(s => s.OverallAccuracy);
            return Math.Round(newer - older, 1);
        }
    }
}

using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using PickleballWebApp.Services;

namespace PickleballWebApp.Middleware
{
    public class PageTrackingMiddleware
    {
        private readonly RequestDelegate _next;

        // Maps URL path prefixes to readable Vietnamese page titles
        private static readonly Dictionary<string, string> _pageTitles = new(StringComparer.OrdinalIgnoreCase)
        {
            { "/MotionCompare", "Phân tích động tác AI" },
            { "/MyProgress",    "Tiến độ luyện tập" },
            { "/Techniques/Serve",     "Kỹ thuật Serve" },
            { "/Techniques/Return",    "Kỹ thuật Return" },
            { "/Techniques/Forehand",  "Kỹ thuật Forehand" },
            { "/Techniques/Backhand",  "Kỹ thuật Backhand" },
            { "/Techniques/Volley",    "Kỹ thuật Volley" },
            { "/Techniques/Dink",      "Kỹ thuật Dink" },
            { "/Techniques/DropShot",  "Kỹ thuật Drop Shot" },
            { "/Techniques/Drive",     "Kỹ thuật Drive" },
            { "/Techniques/Lob",       "Kỹ thuật Lob" },
            { "/Techniques/Smash",     "Kỹ thuật Smash" },
            { "/Techniques/BlockShot", "Kỹ thuật Block Shot" },
            { "/Techniques/ErneShot",  "Kỹ thuật Erne Shot" },
            { "/Exercises",            "Bài tập" },
            { "/Rules",                "Luật chơi" },
            { "/History",              "Lịch sử Pickleball" },
            { "/PaddleBeginners",      "Vợt cho người mới" },
            { "/PaddleIntermediate",   "Vợt trung cấp" },
            { "/CourtsHanoi",          "Sân ở Hà Nội" },
            { "/CourtsHCM",            "Sân ở TP.HCM" },
            { "/NewsDomestic",         "Tin trong nước" },
            { "/NewsInternational",    "Tin quốc tế" },
            { "/",                     "Trang chủ" },
        };

        public PageTrackingMiddleware(RequestDelegate next)
        {
            _next = next;
        }

        public async Task InvokeAsync(HttpContext context, UserDataService userDataService)
        {
            await _next(context);

            // Only track GET requests for authenticated users on HTML pages
            if (context.Request.Method != "GET") return;
            if (!context.User.Identity?.IsAuthenticated ?? true) return;

            var path = context.Request.Path.Value ?? "/";

            // Skip static files, API calls, admin, login
            if (path.StartsWith("/lib/", StringComparison.OrdinalIgnoreCase)) return;
            if (path.StartsWith("/css/", StringComparison.OrdinalIgnoreCase)) return;
            if (path.StartsWith("/js/",  StringComparison.OrdinalIgnoreCase)) return;
            if (path.StartsWith("/images/", StringComparison.OrdinalIgnoreCase)) return;
            if (path.StartsWith("/Admin", StringComparison.OrdinalIgnoreCase)) return;
            if (path.StartsWith("/Login", StringComparison.OrdinalIgnoreCase)) return;
            if (path.Contains('.')) return; // static file by extension

            var title = ResolveTile(path);
            var username = context.User.Identity!.Name ?? "unknown";

            try
            {
                userDataService.RecordPageVisit(username, path, title);
            }
            catch
            {
                // Never crash the request due to tracking failure
            }
        }

        private static string ResolveTile(string path)
        {
            // Longest prefix match
            string best = "Trang";
            int bestLen = 0;
            foreach (var (key, title) in _pageTitles)
            {
                if (path.StartsWith(key, StringComparison.OrdinalIgnoreCase) && key.Length > bestLen)
                {
                    best = title;
                    bestLen = key.Length;
                }
            }
            return best;
        }
    }
}

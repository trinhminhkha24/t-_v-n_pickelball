using System;

namespace PickleballWebApp.Models
{
    public class PageVisit
    {
        public DateTime VisitedAt { get; set; }
        public string PagePath { get; set; } = string.Empty;
        public string PageTitle { get; set; } = string.Empty;
    }
}

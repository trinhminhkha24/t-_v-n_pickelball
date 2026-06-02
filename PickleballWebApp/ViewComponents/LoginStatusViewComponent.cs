using Microsoft.AspNetCore.Mvc;
using System.Threading.Tasks;

namespace PickleballWebApp.ViewComponents
{
    public class LoginStatusViewComponent : ViewComponent
    {
        public IViewComponentResult Invoke()
        {
            return View();
        }
    }
}

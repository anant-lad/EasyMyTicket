# EasyMyTicket Frontend

A modern, professional SaaS-style React frontend for the EasyMyTicket ticket management system.

## 🎨 Design Features

- **Modern SaaS UI**: Clean, professional design with light colors
- **Role-Based Access**: Separate dashboards for Users and Technicians
- **Responsive Design**: Mobile-friendly layout
- **Tailwind CSS**: Modern utility-first styling
- **TypeScript**: Type-safe development

## 📁 Project Structure

```
src/
├── components/
│   ├── common/          # Reusable UI components
│   ├── dashboard/       # Dashboard components
│   │   ├── UserHome.tsx
│   │   └── TechnicianHome.tsx
│   ├── tickets/         # Ticket management components
│   │   ├── CreateTicket.tsx
│   │   ├── TicketList.tsx
│   │   └── TicketDetail.tsx
│   ├── technicians/     # Technician management
│   └── organizations/   # Organization management
├── context/
│   └── AuthContext.tsx  # Authentication context
├── pages/
│   ├── Login.tsx        # Login page with role selection
│   ├── UserDashboard.tsx
│   └── TechnicianDashboard.tsx
├── services/
│   ├── api.ts           # Axios instance
│   ├── tickets.ts       # Ticket API calls
│   ├── organizations.ts # Organization API calls
│   ├── technicians.ts   # Technician API calls
│   └── feedback.ts      # Feedback API calls
├── types/
│   └── index.ts         # TypeScript type definitions
├── App.tsx              # Main app with routing
└── index.tsx            # Entry point
```

## 🚀 Getting Started

1. **Install dependencies** (if not already done):
```bash
cd frontend
npm install
```

2. **Start the development server**:
```bash
npm start
```

3. **Open your browser**:
Navigate to `http://localhost:3000`

## 🔐 Authentication

### Login Flow
1. User selects role (User or Technician)
2. Enters email and password
3. System authenticates against database
4. Redirects to appropriate dashboard

### User Dashboard Routes
- `/user/dashboard` - Overview with stats
- `/user/tickets` - List all user tickets
- `/user/tickets/:ticketNumber` - Ticket details
- `/user/create-ticket` - Create new ticket

### Technician Dashboard Routes
- `/technician/dashboard` - Overview with stats
- `/technician/tickets` - All tickets
- `/technician/my-tickets` - Assigned tickets only
- `/technician/tickets/:ticketNumber` - Ticket details with actions
- `/technician/technicians` - Technician management
- `/technician/analytics` - Analytics dashboard

## 🎨 Color Scheme

- **Primary**: Blue (#3B82F6) - Main actions, links
- **Secondary**: Green (#10B981) - Success states
- **Accent**: Amber (#F59E0B) - Warnings, highlights
- **Background**: Light Gray (#F9FAFB)
- **Surface**: White (#FFFFFF)

## 📡 API Integration

All API calls are centralized in the `services/` directory:
- Base URL: `http://localhost:5000/api` (configurable via env)
- Automatic token handling
- Error interception and handling

## 🔧 Key Features

### User Features
- Create tickets with file uploads
- View ticket status and details
- Track ticket history
- View resolution steps

### Technician Features
- View all tickets
- Filter and search tickets
- Update ticket status
- Resolve tickets
- View assigned tickets
- Technician management
- Analytics dashboard

## 🛠️ Technologies Used

- **React 19** - UI library
- **TypeScript** - Type safety
- **React Router** - Routing
- **React Query** - Data fetching
- **React Hook Form** - Form handling
- **Tailwind CSS** - Styling
- **Heroicons** - Icons
- **React Hot Toast** - Notifications
- **Axios** - HTTP client

## 📝 Environment Variables

Create a `.env` file in the frontend directory:

```env
REACT_APP_API_URL=http://localhost:5000/api
```

## 🎯 Next Steps

1. Test the login flow
2. Create test users/technicians in the database
3. Test ticket creation
4. Test ticket management features

## 🐛 Troubleshooting

If you see errors:
1. Make sure backend is running on port 5000
2. Check browser console for errors
3. Verify API endpoints are correct
4. Ensure database has test users/technicians

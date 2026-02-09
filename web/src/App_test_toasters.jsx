import { useNotifications } from './hooks/useNotifications';
import { ToastContainer } from './components/ToastContainer';

function App() {
  const { addNotification } = useNotifications();

  const testAlert = () => {
    addNotification({
      severity: 'error',
      title: 'Тестовый алерт',
      message: '/sensing/lidar/top/rslidar_node отключилась',
      alertType: 'node_inactive'
    });
  };

  return (
    <div className="h-screen bg-gray-900 text-white p-4">
      <h1 className="text-2xl mb-4">Toast Test</h1>
      
      <div className="flex gap-2">
        <button 
          onClick={testAlert}
          className="bg-red-600 hover:bg-red-700 px-4 py-2 rounded"
        >
          Test Error
        </button>
        
        <button 
          onClick={() => addNotification({
            severity: 'warning',
            title: 'Предупреждение',
            message: 'Топик /localization/pose не найден',
            alertType: 'missing_topic'
          })}
          className="bg-yellow-600 hover:bg-yellow-700 px-4 py-2 rounded"
        >
          Test Warning
        </button>
        
        <button 
          onClick={() => addNotification({
            severity: 'info',
            title: 'Нода восстановилась',
            message: '/planning/mission_planner',
            alertType: 'node_recovered'
          })}
          className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded"
        >
          Test Info
        </button>
      </div>

      <ToastContainer />
    </div>
  );
}

export default App;
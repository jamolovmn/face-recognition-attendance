<?php

declare(strict_types=1);

namespace OCA\FaceAttendance\Controller;

use OCA\FaceAttendance\AppInfo\Application;
use OCA\FaceAttendance\Service\AttendanceService;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Db\DoesNotExistException;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\FrontpageRoute;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\Attribute\NoCSRFRequired;
use OCP\AppFramework\Http\FileDisplayResponse;
use OCP\AppFramework\Http\NotFoundResponse;
use OCP\AppFramework\Http\Response;
use OCP\AppFramework\Http\TemplateResponse;
use OCP\Files\NotFoundException;
use OCP\IRequest;
use OCP\IUserSession;
use OCP\Util;

class PageController extends Controller {
	public function __construct(
		string $appName,
		IRequest $request,
		private AttendanceService $service,
		private IUserSession $userSession,
	) {
		parent::__construct($appName, $request);
	}

	#[NoAdminRequired]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'GET', url: '/')]
	public function index(): TemplateResponse {
		$allowed = $this->service->canAccess($this->userSession->getUser());
		if ($allowed) {
			Util::addScript(Application::APP_ID, 'main');
			Util::addStyle(Application::APP_ID, 'main');
		}
		$response = new TemplateResponse(Application::APP_ID, 'main', ['allowed' => $allowed]);
		if (!$allowed) {
			$response->setStatus(Http::STATUS_FORBIDDEN);
		}
		return $response;
	}

	#[NoAdminRequired]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'GET', url: '/snapshot/{id}', requirements: ['id' => '\d+'])]
	public function snapshot(int $id): Response {
		if (!$this->service->canAccess($this->userSession->getUser())) {
			return new Response(Http::STATUS_FORBIDDEN);
		}
		try {
			$file = $this->service->snapshot($id);
		} catch (NotFoundException|DoesNotExistException) {
			return new NotFoundResponse();
		}
		$response = new FileDisplayResponse($file, Http::STATUS_OK, ['Content-Type' => 'image/jpeg']);
		$response->cacheFor(3600, false, true);
		return $response;
	}
}
